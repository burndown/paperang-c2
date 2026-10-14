# paperang-c2

[English](README.md) · [协议文档](docs/PROTOCOL.zh-CN.md) · [局域网打印服务 / AirPrint](docs/DEPLOY.zh-CN.md)

不用手机 App，在 Mac 或 Linux 上直接打印到 **作业帮喵喵机 C2**（Paperang C2，4 英寸蓝牙热敏打印机）：命令行、一个小网页，还有一条命令就能装好的**局域网打印服务**，家里所有手机、电脑都能打，包括 iPhone / iPad 的**系统“打印”对话框**（AirPrint）。

> **非官方项目。**这是对作者自己设备做的互操作研究，与厂商无关，未经厂商认可，产品名归各自所有者。不含任何厂商代码。个人项目，不提供任何担保。

## 验证状态（如实说明）

下面的“已验证”都是在**一台 C2、固件 `01.00.22`、4 英寸（101.6 mm）纸卷、打印机设置为 110 mm** 上做的：

| 已验证 | 没验证 |
|---|---|
| 在 macOS（Python 3.9，Apple 芯片）和 Debian 13（Python 3.13，Intel AX210 蓝牙）上打印 | Windows、树莓派（理论上可以，也是 BlueZ）、其他 Linux 发行版 |
| 命令行、网页（桌面浏览器）、蓝牙地址扫描 | 手机浏览器上的网页（只在桌面浏览器里按手机宽度看过排版） |
| Debian 13 上用 systemd 部署的局域网打印服务 | Android / Windows 打印到这台 AirPrint 打印机 |
| iPhone 的 AirPrint（能发现、能打印） | macOS 用“添加打印机”添加 |
| 110 mm 设置配 4 英寸纸卷 | 57 mm、79 mm 纸宽，其他喵喵机型号或固件 |
| | USB（C2 有 USB 口，但没有验证过通过它通信）、调浓度指令 |

如果你在别的环境试了，欢迎开 issue 说说结果。[docs/HARDWARE-TESTING.md](docs/HARDWARE-TESTING.md)（英文）里有可以打印出来检查自己机器的校准页。

## 为什么要做这个

C2 **不说**老款喵喵机的协议，现有的开源工具都是按老协议写的，对 C2 什么也打不出来。它用的是更新的帧格式（`A5 … 5A`），对别的指令一律沉默。[协议文档](docs/PROTOCOL.zh-CN.md)里写了协议、打印流程，以及决定纸上是否完整的时序规则（过早断开连接会悄悄丢掉没印完的行）。

## 上手：在自己的电脑上打印

需要 Python 3.9+ 和蓝牙。

```bash
git clone https://github.com/burndown/paperang-c2.git
cd paperang-c2
pip install .            # 需要较新的 pip：python3 -m pip install --upgrade pip（旧的 pip 21.2 会悄悄漏装命令）
                         # 或者 pip install -r requirements.txt 然后用 python3 -m paperang_c2
```

1. 打开打印机，并**把手机、平板上的厂商 App 和蓝牙关掉**：打印机同一时间只和一个设备通信。
2. **macOS**：在 系统设置 → 蓝牙 里配对一次（系统会说它是打印机，不用管）。**Linux：**不需要配对也不需要信任，`paperang-c2 scan` 能找到地址。
3. 在**终端 App 里**运行（macOS 上进程需要蓝牙权限，只有终端能弹出授权）：

```bash
paperang-c2 scan                                  # 显示蓝牙地址
paperang-c2 info                                  # 型号、固件、电量、纸宽（macOS 会自动选已配对的）
paperang-c2 --addr AA:BB:CC:DD:EE:FF info        # 或者指定地址（也可以设环境变量 PAPERANG_ADDR）
paperang-c2 text "你好 C2"                        # 文字，支持中文；--size 56 --align center
paperang-c2 image photo.jpg                       # 图片；文字、线稿用 --mode threshold
paperang-c2 test                                  # 打一张小测试页
paperang-c2 serve                                 # 网页 http://127.0.0.1:8765/
```

`--preview out.png` 只渲染成图，不连蓝牙、不出纸。打印后会故意多等十几秒才断开，原因见时序规则。

## 上手：全家共享的打印服务

在打印机旁放一台带蓝牙的 Linux 机器（小主机、树莓派、旧笔记本），就能在局域网里共享它：任何浏览器可用的网页、一个小 HTTP 接口，以及一台出现在 iPhone / iPad / Mac 打印对话框里的 **AirPrint** 打印机。安装脚本支持 Debian、Ubuntu、树莓派 OS。

```bash
git clone https://github.com/burndown/paperang-c2.git
cd paperang-c2
sudo ./deploy/install.sh            # 扫描打印机，装依赖，装两个 systemd 服务
```

装好后打开 `http://<那台机器>:8765/`，或者在 iPhone 的 分享 → 打印 里选 **Paperang C2**。

选项、更新、卸载、其他系统的手动安装见 [docs/DEPLOY.zh-CN.md](docs/DEPLOY.zh-CN.md)。ESP32 板子做不了这个桥，除非带经典蓝牙（原版 ESP32 可以，S3、C3、C6 只有 BLE）。

**服务没有任何认证，只在你信任的网络里使用。**

## 从 iPhone / iPad 打印

详见 [docs/AIRPRINT.md](docs/AIRPRINT.md)（英文）。踩坑得到的要点：

- 图要做成**竖的**（高大于宽）。iOS 会把横图、近似正方形的图自动转 90°。
- 纸张选 **A4**（或信纸）。选 4×6 时，iOS 在发给服务器之前就把图裁掉了（A4 测过，信纸没测）。
- 服务器会自动裁掉页面白边、缩放到纸宽，所以选 A4 不会浪费纸。

## 容易踩的坑

- **一次只能一个设备连。**手机 App 哪怕在后台开着也会占住它。两台电脑轮流用也要隔几秒。
- **纸宽。**固件报告的是“设置”（110 mm = 1248 点），不是实际的纸卷。4 英寸纸卷只有大约前 1200 点在纸上，之后的内容印到纸外面。工具默认把内容限制在 12–1188 点；纸卷更宽时设 `PAPERANG_PAPER_WIDTH_MM`。[怎么量。](docs/HARDWARE-TESTING.md)
- **时序。**打印机是在*收到*数据时回确认，不是印完时。纸没走完就断开蓝牙，它会丢掉没印的行；断开后一秒内重连会被重置。代码里已经处理；自己写客户端请读[时序规则](docs/PROTOCOL.zh-CN.md)。
- **macOS 权限。**macOS 上进程需要蓝牙权限，要从终端 App 运行，不能放后台（后台进程会被系统直接终止且不报错）。

## 目录结构

```
paperang_c2/protocol.py    帧与指令（纯函数，只产生字节）
paperang_c2/device.py      查询与打印流程（背靠背发送、核对确认、保持连接）
paperang_c2/bt_macos.py    macOS 的 RFCOMM（IOBluetooth / PyObjC）
paperang_c2/bt_linux.py    Linux 的 RFCOMM（BlueZ 套接字）
paperang_c2/transport.py   选传输、用锁串行化任务、重连间隔、扫描
paperang_c2/render.py      文字/图片 → 1 位点阵、可打印区域
paperang_c2/raster.py      AirPrint 栅格（URF / PWG）解码
paperang_c2/ipp.py         把 AirPrint 任务变成打印（裁边、缩放到纸宽）
paperang_c2/server.py      网页 + HTTP 接口          paperang_c2/web/index.html
deploy/                    install.sh、systemd 模板、IPP 打印机配置
tools/testpages.py         校准页
docs/                      协议、部署、AirPrint、硬件测试
tests/                     单元测试（python3 -m unittest discover -s tests）
```

## 待办

按有用程度大致排序：AirPrint 自动转正横图（截图）；缩短现在刻意取保守的等待时间；找到真正的“打印完成”信号；验证协议 2 能不能走 USB；验证调浓度指令和 57 / 79 mm 纸宽；在其他喵喵机型号上测试。

## 许可证

MIT，见 [LICENSE](LICENSE)。
