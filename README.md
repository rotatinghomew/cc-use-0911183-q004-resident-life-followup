# 离院业务服务

现有功能是入住资格、分项问卷的月度描述统计、纵向分析、补访名单与访员派单。离院日不再具备普通随访资格；拒访阻止后续自动联系，未联系上只触发间隔限制，无效联系方式在更正前阻止自动联系。问卷按 self、family、assisted 保留回答身份，不自动换算。`POST /api/response` 保存问卷；`POST /api/assign` 接受 resident、interviewer、date；`POST /api/contact-result` 接受 job、result（responded、unreachable、refused、invalid）。

## 启动与核对

使用 Python 3.11 或更高版本。现有服务采用标准库运行；数值分析所需的固定版本工具列在 requirements.txt，部署准备时运行 `python3 -m pip install -r requirements-build.txt -r requirements.txt`，构建前端和打包后端的固定版本见 requirements-build.txt；依赖准备完毕后，测试、构建和运行均可断网进行。无需真实个人信息、凭据或远程数据源。

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q followup tests
python3 -m build --wheel --no-isolation
python3 -m followup check
python3 -m followup demo
python3 -m followup load --database /tmp/followup-business.sqlite3 --input examples/operations.json
python3 -m followup serve --database /tmp/followup-business.sqlite3
```

服务默认监听本机 8765 端口，`--port` 可指定其他端口。健康检查为 `GET /health`，`GET /api/summary` 返回当前已有业务汇总。未指定数据库时，demo 和 check 使用隔离的临时数据库；serve 若需保留修改须传入数据库路径。已有数据库不重复装载同一类样例。examples/operations.json 是较大的一组历史运营资料，可用 load 命令在事务内载入；按类型和编号更正同名记录，未出现的记录保持不变。所有资料采用固定来源生成且不包含对未来分析结论的预设值。

## 纵向分析

`GET /api/longitudinal?month=2026-11&window=6` 返回以 month 结尾的逐月序列与两期比较；`from`、`to` 可指定比较月份，默认窗口内最近两期。

- 分析对象按入住与随访资格逐月确定，不从已答问卷倒推；未答者按原因列出（未同意、无联系方式、拒访、联系方式无效、暂时住院、联系间隔未满、已联系待登记、可联系未尝试）。
- 分项缺答的问卷仍按已答分项计分，并单列部分缺答数量；回答身份切换不与同一测量拼接，跨身份变化单独列示，同一人同月多种身份记为 mixed。
- 正式离院、转院、死亡（left_reason：discharge、transfer、deceased，缺省未注明）自离院日起退出后续各期对象与补访池，历史各期仍保留其观察；暂时住院、暂时未联系上的人留在队列中，可恢复随访。
- 两期比较把观察均值变化分解为同身份留答者变化、身份切换者差异、新答者带入、流失者带走与占比机械影响，各分量之和恒等于观察变化；失访者的变化无法由现有资料识别，sensitivity 给出失访假设情景（最低、最高、当期已答均值、本人最近观察）与任意填补下的理论边界，只有边界同号时才说明方向对失访假设稳健，且不代表失访者真实改善。

## 补访名单

`POST /api/plan` 接受 date、slots、可选 site，生成名单并在同一事务内创建联系安排；`GET /api/plans` 查看历史名单。名额优先分配给影响当前比较判断的缺口（长期未答、无基线、回答方式缺少代表、历史得分与当前差距较大、未接通待重试），不按最低分排队；只从当日可联系对象中选择（同意、联系方式可用、间隔已满、无未结束安排、当日未处于暂时离院），并核对访员院区覆盖，名单内按访员负载均衡派单。同一老人同一日期只有一条安排，未结束的安排阻止重复派访，不同院区的名单不会重复派访。名单理由在生成时固定，访员报回结果写入新记录，影响后续资格与分析证据，但不改写旧名单。

本服务为服务质量分析，不输出诊断或个人照护建议。

## 数据与运行边界

fixtures 中均为本地合成业务资料，员工、家庭和院区编号不对应真实对象。JSON 里的空值表示未记录，不代表零；日期采用 ISO 格式。金额以分保存，工时以分钟保存。每类记录有独立编号，写入同编号用于业务更正，revision 用于并发修改核对。

业务状态由 SQLite 保存，记录批量更正在单一事务内提交。接口使用 UTF-8 JSON，未知资源返回 404，非法数据返回 400，版本冲突返回 409。服务不进行临床诊断，也不自动改变实际服务安排。测试使用临时数据库和系统分配的空闲端口，彼此隔离，不访问公网。运行日志、数据库和依赖缓存不应提交到仓库。
