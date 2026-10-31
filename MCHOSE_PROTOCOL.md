# 迈从电量协议调查（2026-10-28）

## 当前结论

本机存在 `3837:201B`、产品名 `MCHOSE 2.4G Wireless`、厂商名
`SINOWEALTH` 的接收器。官方脚本将该 PID 对应到 G87 V2 系列
（`MCHOSE 2.4G Wireless-G87_V2$$$14391$$$8219`）。具体实物型号尚未由用户确认。

已从官方网页驱动提取查询与解析逻辑，并在唤醒的实机上连续两次读到 54%。
该结论只覆盖本机的 `3837:201B` 接收器，不能宣称支持迈从全系列。
协议已通过稳定 key `mchose_keyboard` 加入 `device_plugins.py`。

## 官方来源与复现依据

- https://www.mchose.com.cn/
- https://www.mchose.com.cn/assets/purify.es-D9IeuU3Y.js
- 本次下载副本位于 `debug/mchose/driver.js`（不提交 Git）。文件名可能随官网发布变化。
- 搜索 `8219` 可见型号映射与 `usagePage:65282`（`0xFF02`）。
- 搜索 `getBattery` 可见 `wirelessCommand`、`getBatteryWirelessParser`。
- `readCommand` 拼接字节求和校验后，移除报文第一字节，调用 WebHID
  `sendReport(0x13, payload)`；Windows 输出需保留报告 ID。
- `handleCommandResponse` 校验命令、分片序号，再从不含报告 ID 的数据中
  提取 `slice(4,-1)`；电量解析器读取 `uint8 batteryLevel`、
  高 4 位 `fullStatus`、低 4 位 `chargeStatus`。

## 本机接口与协议

查询接口：UsagePage `0xFF02`，Usage `0x0002`，Input/Output 均为 20 字节。
其他 Feature 接口（1032、8、6 字节）没有被用于此次查询。

请求（完整 Windows 报文）：

```text
13 4A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E
```

末字节为前 19 字节之和的低 8 位。
单包回复：`[0]=13 [1]=4A [2]=01(总包数) [3]=00(序号)`；
`[5]` 为百分比，`[6]` 高 4 位为充满状态、低 4 位为充电状态（`1` 表示充电）。
末字节同样是此前 19 字节之和的低 8 位。

## 实测

通过独立异步读取句柄先建立接收，再发送查询。
键盘未唤醒时，分别以 WriteFile 和 HidD_SetOutputReport 发送均未收到 Input Report。
键盘唤醒后以 WriteFile 连续两次收到：

```text
13 4A 01 00 02 36 00 00 00 00 00 00 00 00 00 00 00 00 00 96
```

`0x36 = 54`，两次结果一致，`0x96` 与回复校验和一致。没有发送设置、配对、
固件或未知唤醒命令。
受限执行环境只能枚举路径而读不到属性；本次实际设备访问使用了获准的非受限执行。

## 后续复测

设备在 2.4G 模式唤醒后运行（不产生缓存文件）：

```powershell
.\.package-venv\Scripts\python.exe -B mchose_probe.py --query
.\.package-venv\Scripts\python.exe -B mchose_probe.py --query --transport hidd
```

默认不加 `--query` 只枚举目标接口。诊断只打印到控制台；需要保存输出时放入
`debug/`。先记录 M HUB 电量，避免它与诊断同时争用接收器。
后续仍可对比 M HUB 显示，并验证充电和充满状态位。休眠时无回复、唤醒后恢复读取已验证。
