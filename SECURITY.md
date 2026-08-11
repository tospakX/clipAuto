# Security Policy

Please report security issues privately through GitHub's **Security → Report a vulnerability**
feature rather than opening a public issue. Include affected versions, reproduction steps, and
the potential impact.

The CLI executes local media tools and contacts the configured Ollama endpoint. Review URLs and
custom endpoint values before use, keep `yt-dlp`, FFmpeg, Ollama, and Python dependencies current,
and do not commit downloaded media or model caches.
