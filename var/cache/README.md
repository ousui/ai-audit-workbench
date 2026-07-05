# var/cache

`var/cache/` 存放可重建缓存，不提交。

适合存放工具规则库、漏洞库、下载缓存等，例如：

```text
var/cache/tools/semgrep/
var/cache/tools/trivy/
var/cache/tools/dependency-check/
```

缓存状态摘要可以记录到 `local/registry/tools/`，但实际缓存文件放在这里。
