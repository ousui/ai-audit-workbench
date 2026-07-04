# Install Guide

本文件记录 AI Audit Workbench 的工具安装建议。

本文件只提供团队通用安装参考，不记录任何审计人员本机路径。

本机真实工具路径、SDK 实例、当前激活版本和检测结果由 env-check 生成到本地结果文件中，不提交到 Git。

## 1. 当前范围

当前版本只覆盖 core 工具安装建议。

core 工具是工作台启动和基础审计流程所必需的工具。

缺少 core 工具时，工作台应阻断启动或阻断关键流程。

当前 core 工具包括：

- git
- rg / ripgrep
- python3
- bash
- find
- grep
- sed
- awk
- jq
- tar

其中：

- git、rg、python3、bash、find、grep、sed、awk 是基础必备。
- jq、tar 是推荐工具，缺失时可记录为 missing，但不一定阻断整个工作台。

## 2. 安装原则

### 2.1 优先使用用户环境

推荐优先使用用户环境安装工具，避免污染系统环境。

推荐工具管理方式：

- macOS：Homebrew、mise、asdf
- Linux：系统包管理器、mise、asdf
- Windows：winget、Git for Windows、WSL

### 2.2 多版本 SDK 后续交给环境管理器

Go、Java、Node、Python 等多版本 SDK 后续建议使用以下工具管理：

- mise
- asdf
- sdkman
- nvm
- pyenv

当前 core 阶段只要求 python3 可运行。

后续技术栈工具矩阵会单独定义 Go / Java / Node / PHP / Flutter 等 SDK。

### 2.3 不默认联网执行审计

安装工具可能需要联网，但审计执行默认不应联网。

联网安装、联网下载规则、联网查询漏洞库、联网访问外部服务，均应作为单独授权事项处理。

### 2.4 不写入被审项目源码

工具安装和检测不得写入被审项目源码。

审计过程产物只能写入：

- runs/
- tmp/
- deliveries/
- 工作台配置允许的缓存目录

## 3. macOS 安装建议

### 3.1 安装 Homebrew

如果未安装 Homebrew，可参考团队允许的方式安装。

安装完成后确认：

```bash
brew --version
```

Apple Silicon 常见路径：

```text
/opt/homebrew/bin/brew
```

Intel Mac 常见路径：

```text
/usr/local/bin/brew
```

### 3.2 安装 core 工具

```bash
brew install git
brew install ripgrep
brew install python
brew install bash
brew install jq
```

macOS 通常自带以下工具：

```text
find
grep
sed
awk
tar
```

如需要 GNU 版本，可选安装：

```bash
brew install findutils
brew install grep
brew install gnu-sed
brew install gawk
brew install gnu-tar
```

注意：GNU 工具安装后可能以 `gfind`、`ggrep`、`gsed`、`gawk`、`gtar` 等名称存在。

env-check 应记录实际可执行文件路径和命令名称。

### 3.3 推荐安装 mise

mise 可用于后续管理 Python、Go、Node、Java 等多版本 SDK。

```bash
brew install mise
```

确认：

```bash
mise --version
```

示例：

```bash
mise use -g python@3.11
```

### 3.4 推荐安装 asdf

如团队已有 asdf 体系，也可以使用 asdf。

```bash
brew install asdf
```

确认：

```bash
asdf --version
```

## 4. Linux 安装建议

## 4.1 Debian / Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y git ripgrep python3 python3-venv python3-pip bash findutils grep sed gawk jq tar
```

确认：

```bash
git --version
rg --version
python3 --version
bash --version
jq --version
tar --version
```

## 4.2 RHEL / Fedora / CentOS Stream

```bash
sudo dnf install -y git ripgrep python3 python3-pip bash findutils grep sed gawk jq tar
```

确认：

```bash
git --version
rg --version
python3 --version
bash --version
jq --version
tar --version
```

## 4.3 推荐安装 mise

Linux 下可按团队允许方式安装 mise。

安装完成后确认：

```bash
mise --version
```

## 4.4 推荐安装 asdf

如团队已有 asdf 体系，也可以使用 asdf。

安装完成后确认：

```bash
asdf --version
```

## 5. Windows 安装建议

Windows 建议优先使用以下两种方式之一：

1. Git for Windows + PowerShell
2. WSL

如果审计对象包含大量 Linux / Go / Java / Node 后端项目，推荐使用 WSL。

## 5.1 安装 Git for Windows

```powershell
winget install Git.Git
```

安装后确认：

```powershell
git --version
```

Git for Windows 会提供 Git Bash，其中通常包含 bash、find、grep、sed、awk、tar 等基础工具。

## 5.2 安装 ripgrep

```powershell
winget install BurntSushi.ripgrep.MSVC
```

确认：

```powershell
rg --version
```

## 5.3 安装 Python

```powershell
winget install Python.Python.3.11
```

确认：

```powershell
python --version
```

或：

```powershell
python3 --version
```

env-check 应同时检测 `python` 和 `python3`，并记录实际可用命令。

## 5.4 安装 jq

```powershell
winget install jqlang.jq
```

确认：

```powershell
jq --version
```

## 5.5 使用 WSL

启用 WSL 后，可在 Ubuntu 子系统内按 Debian / Ubuntu 安装建议执行。

```bash
sudo apt-get update
sudo apt-get install -y git ripgrep python3 python3-venv python3-pip bash findutils grep sed gawk jq tar
```

## 6. core 工具验证命令

安装完成后，可手动执行以下命令确认基础工具状态：

```bash
git --version
rg --version
python3 --version
bash --version
find --version
grep --version
sed --version
awk --version
jq --version
tar --version
```

注意：

macOS 系统自带的 find、sed、awk、tar 可能不支持 `--version`。

env-check 脚本后续应兼容以下情况：

* 命令存在但不支持 `--version`
* 命令存在但版本输出在 stderr
* Windows 下命令名称不同
* Git Bash / WSL / PowerShell 行为差异
* GNU 工具和 BSD 工具输出差异

因此检测逻辑不应只依赖 `--version` 是否成功。

## 7. 工具缺失处理策略

### 7.1 required_for_workbench

缺失后应阻断工作台启动。

当前包括：

* git
* rg
* python3
* bash
* find
* grep
* sed
* awk

### 7.2 recommended_for_static

缺失后不阻断工作台，但应记录为 missing，并说明影响。

当前包括：

* jq
* tar

### 7.3 后续技术栈工具

Go、Java、Node、PHP、Flutter、Android、iOS、DAST、REVERSE 等工具后续通过工具矩阵扩展。

缺少非当前技术栈工具时，不应阻断当前项目审计。

例如：

* 审计 Go 项目时，缺少 Java 不应阻断。
* 审计 Java 项目时，缺少 Go 不应阻断。
* 当前 SAST-only 阶段，缺少 Burp Suite、MobSF、jadx 不应阻断。

## 8. 路径记录原则

env-check 可以记录本机真实路径，但本机检测结果不得提交到 Git。

业务报告中不得出现：

* 本机绝对路径
* 用户 Home 路径
* Token
* 密钥
* 证书内容
* 私有仓库地址中的敏感信息

路径在业务方报告中应脱敏为：

```text
<LOCAL_USER_PATH>
<WORKBENCH_DIR>
<PROJECT_DIR>
<RUN_DIR>
```

## 9. 推荐提交策略

本文件属于团队共享文档，应提交到 Git。

以下文件不应提交：

```text
env/*.local.json
env/ENV_CHECK_RESULT.json
env/ENV_CHECK_RESULT.*.json
```

如需提供示例，应使用：

```text
env/ENV_CHECK_RESULT.example.json
```

## 10. 后续扩展

后续版本将逐步补充：

* common_static 工具安装建议
* Go 工具安装建议
* Java 工具安装建议
* Node / 前端工具安装建议
* PHP 工具安装建议
* Flutter 工具安装建议
* Android 逆向工具安装建议
* iOS / macOS 工具安装建议
* DAST 工具安装建议
* sandbox / container 工具安装建议