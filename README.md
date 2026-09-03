# 十分吸引完整历史 RSS

从 `shifenxiyin.com` 的公开 sitemap 和单集 JSON-LD 元数据生成完整、可播放的 RSS 2.0 feed。音频文件不复制、不重新托管，`enclosure` 直接指向原发布方公开地址。

## 订阅

GitHub Pages 启用后：

```text
https://jontian.github.io/shifenxiyin-rss/feed.xml
```

## 自动更新

GitHub Actions 每 6 小时检查一次，并支持手动运行。脚本只使用 Python 标准库：

```bash
python scripts/build_feed.py
```

## 注意

- 私有仓库能否启用 GitHub Pages 取决于 GitHub 账户方案。
- Pages 发布地址是公开的，适合播客客户端直接订阅。
- 若源站结构或公开音频 URL 发生变化，工作流会失败并保留上一次可用 feed。
- 本项目仅建立公开内容索引，不包含或重新分发音频文件。
