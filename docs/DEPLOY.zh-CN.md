# 局域网打印服务（网页、HTTP 接口、AirPrint）

[English](DEPLOY.md)

打印机只说经典蓝牙。想让网络里所有设备都能打，就在打印机旁放一台带蓝牙适配器的 Linux 小机器，在上面跑两个服务：

| 服务 | 提供什么 | 默认端口 |
|---|---|---|
| `paperang-c2` | 一个网页、一个小 HTTP 接口 | 8765 |
| `paperang-ipp` | 一台叫 **Paperang C2** 的 AirPrint / IPP Everywhere 打印机（用 mDNS 广播） | 8631 |

在 Debian 13（Intel AX210 蓝牙）上测试过。Debian、Ubuntu、树莓派 OS 理论上都行（树莓派没测过）。这台机器要在离打印机约 10 米以内，最好中间没有墙。

**没有任何认证。**网络里任何人都能打印（也能浪费纸）。只在信任的网络使用，或放在带认证的反向代理后面。

ESP32 做不了这件事，除非支持经典蓝牙：原版 ESP32 可以，S3、C3、C6 不行（只有 BLE）。

## 一条命令安装（Debian / Ubuntu / 树莓派 OS）

```bash
git clone https://github.com/burndown/paperang-c2.git
cd paperang-c2
sudo ./deploy/install.sh
```

运行前：打开打印机，放到这台机器旁边，确认没有手机连着它。脚本会：

1. 安装 `bluez`、`python3-pil`、`poppler-utils`、`fonts-noto-cjk`，以及（AirPrint 用的）`cups-ipp-utils`、`avahi-daemon`；
2. 扫描打印机（约 15 秒）得到蓝牙地址（不需要配对也不需要信任；用 `--addr` 可以跳过扫描）；
3. 写 `/etc/default/paperang-c2`（打印机地址、纸宽）；
4. 安装并启动两个 systemd 服务，用你的普通用户身份、从克隆下来的目录运行；
5. 连一次打印机确认能通，并打印访问地址。

服务**直接从你克隆的目录运行**，所以不要删除或移动这个目录。

选项：

```
--addr AA:BB:CC:DD:EE:FF   跳过扫描（周围有多台打印机，或扫描找不到时用）
--paper-mm 101.6           实际用的纸卷宽度（见下）
--port 8765                网页端口            --ipp-port 8631   AirPrint 端口
--user NAME                服务以哪个用户运行（默认是执行 sudo 的用户）
--allow-host NAME          网页额外接受的主机名（可重复），比如反向代理的域名
--no-web / --no-airprint   只装其中一个服务
--dry-run                  只显示会做什么，不改任何东西
--uninstall                移除服务（已装的软件包和 /etc/default/paperang-c2 保留）
```

### 纸宽

固件报告的是纸宽*设置*（110 mm，1248 点）。如果你的纸卷更窄（“4 英寸”纸卷是 101.6 mm），超出纸边的点会打到空气里，表现为框的右边没有、每行最后一个字被切掉。`--paper-mm`（保存为 `PAPERANG_PAPER_WIDTH_MM`）告诉工具真实宽度，内容会限制在其中，并留 1 mm 边距。想量自己的纸卷，打印 [HARDWARE-TESTING.md](HARDWARE-TESTING.md)（英文）里的页面。

## 怎么用

**网页：**`http://<机器>:8765/`（或 `http://<主机名>.local:8765/`）。输文字或选择/拖入/粘贴图片，看 1:1 预览，点打印。页面跟随浏览器语言（中文/英文）。

**HTTP 接口**（JSON，`Content-Type: application/json`）：

```bash
# 文字
curl -X POST http://<机器>:8765/api/print -H 'Content-Type: application/json' \
     -d '{"kind":"text","text":"你好","size":56,"align":"center"}'

# 图片（base64 data URL），文字、线稿用 "mode":"threshold"，照片用 "dither"
curl -X POST http://<机器>:8765/api/print -H 'Content-Type: application/json' \
     -d "{\"kind\":\"image\",\"image\":\"data:image/png;base64,$(base64 < label.png | tr -d '\n')\",\"mode\":\"threshold\"}"

curl http://<机器>:8765/api/info           # 连接并返回型号、电量、纸宽
```

请求在纸应该走完时返回，通常十几到二十秒。请求逐个处理。网页服务只接受 `Host` 头是 `localhost`、本机主机名、`<主机名>.local` 或主 IP 的请求（见 `--allow-host`），并且只收 `application/json`；这是为了防止浏览器里的某个网页偷偷触发打印，不是认证。

**AirPrint：**在 iPhone、iPad 或 Mac 的打印对话框里选 **Paperang C2**。先读 [AIRPRINT.md](AIRPRINT.md)（英文）：图要竖的，纸张选 A4。

## 放在反向代理后面 / 用子域名访问

网页服务只接受它认识的 `Host` 头（见上文），所以代理如果把原始主机名透传，就要把这个名字放行。以 nginx、
用 `printer.example.lan` 访问为例：

```bash
sudo ./deploy/install.sh --addr AA:BB:CC:DD:EE:FF --allow-host printer.example.lan     # 重复运行是安全的
```

```nginx
server {
    listen 80;
    server_name printer.example.lan;
    client_max_body_size 50m;                      # 图片以 base64 的 JSON 上传
    location / {
        proxy_pass http://127.0.0.1:8765;          # 写 IP:端口，不要写主机名
        proxy_http_version 1.1;
        proxy_set_header Host $host;               # 必须是传给 --allow-host 的名字
        proxy_read_timeout 300s;                   # 一次打印请求要十几到二十秒
    }
}
```

AirPrint 打印机不经过代理：手机通过 mDNS 直接发现它的端口。

## 运维

```bash
systemctl status paperang-c2 paperang-ipp
journalctl -u paperang-c2 -u paperang-ipp -f          # 实时日志
sudo systemctl restart paperang-c2 paperang-ipp
cat /etc/default/paperang-c2                          # 打印机地址、纸宽、AirPrint 是否裁边
```

**更新：**`git pull && sudo systemctl restart paperang-c2 paperang-ipp`（`deploy/` 有改动时重新运行 `sudo ./deploy/install.sh`）。

**不浪费纸地调试 AirPrint：**`touch /tmp/paperang-ipp.dry`。文件存在期间，手机发来的任务不打印，任务属性记到 `/tmp/paperang-ipp.dry.log`，文档复制到 `/tmp/paperang-ipp.dry.d/`。删掉文件恢复打印。平时不保留文档。

## 手动安装（其他发行版）

需要：Python 3.9+、Pillow、BlueZ（`bluetoothctl`）、`fonts-noto-cjk` 或别的中文字体、`pdftoppm`（poppler，处理 PDF）、以及 AirPrint 用的 `ippeveprinter`（CUPS 2.4，Debian 下是 `cups-ipp-utils` 包）和 avahi。

```bash
bluetoothctl scan on                       # 找到地址，Ctrl-C 结束（不需要配对也不需要信任）
PAPERANG_ADDR=AA:BB:CC:DD:EE:FF python3 -m paperang_c2 info          # 必须能打印出型号
PAPERANG_ADDR=AA:BB:CC:DD:EE:FF python3 -m paperang_c2 serve --host 0.0.0.0 --port 8765 --allow-host myserver.local
```

然后改 `deploy/*.service.in` 模板（替换 `@USER@`、`@DIR@`、`@PYTHON@`、`@PORT@`、`@IPP_PORT@`、`@IPPEVE@`、`@ALLOW_HOST_ARGS@`）和 `deploy/paperang-c2.env.example`（放到 `/etc/default/paperang-c2`）。

## 排错

| 现象 | 可能原因和办法 |
|---|---|
| `could not open RFCOMM … timed out` / `Host is down` | 打印机关了或睡着了（约 30 分钟自动关机，按一下按钮），超出范围，或者还连着手机、别的电脑。关掉手机 App，等几秒再试。 |
| 紧接着上一个任务就 `Connection reset by peer` | 断开后一秒内重连。工具自己会等 1.5 秒，不同机器轮流用打印机时会遇到。等几秒。 |
| 打印的开头几行没有 | 纸没走完就断开了连接。除非你实测过，不要缩短 `device.py` 里的等待，见 PROTOCOL 的时序规则。 |
| 框的右边 / 每行最后一个字没有 | 纸卷比打印机设置窄。设 `--paper-mm` / `PAPERANG_PAPER_WIDTH_MM`。 |
| 文字特别小或没有中文 | 机器上没有中文字体（`fonts-noto-cjk`）。工具会直接报错，不会打一张点阵小字。 |
| iPhone 里看不到“Paperang C2” | 手机和服务器要在同一子网，路由器不能屏蔽 mDNS（客户端隔离）。检查 `systemctl status avahi-daemon paperang-ipp`。 |
| iPhone 打出来是转的或被裁 | 见 AIRPRINT.md：图要竖的，纸张选 A4。 |
| 网页提示 `bad host`（HTTP 403） | 你用了不被允许的名字或地址访问。用 `--allow-host` 加上（带 `--allow-host NAME` 重新运行安装脚本）。 |
| 手机打印没任何动静也没报错 | `ls /tmp/paperang-ipp.dry`：调试开关开着，删掉这个文件。 |
