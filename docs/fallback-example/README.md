# Fallback pages: a starting kit

Copy this directory to a path on the server, edit the pages, and point the
service at it:

```ini
# arks-service/.env (bare install) …
FALLBACK_PAGES_DIR=/srv/ark/fallback
# … or docker-arks-service/.env (Docker): the host path, mounted read-only into web
FALLBACK_DIR=/srv/ark/fallback
```

Then restart (bare: `systemctl restart arkservice`; Docker: `make up`). A
superuser sees which pages are in place, with a preview of each, at the bottom
of the Users page. Edits to the files show within a minute without a restart.

| File | Shown for | May use placeholders |
|---|---|---|
| `index.html` | `GET /`, the default page | yes: `{{organisation_name}}`, `{{organisation_website}}`, `{{naa_table}}` |
| `404.html` | any 404: an unknown or unbound ARK, an unknown path | no |
| `403.html` | a public 403 (in practice a failed sign-in form). Signed-in staff who are refused a page see the staff interface's own message instead | no |
| `500.html` | an unhandled error; must not depend on anything but this file | no |
| `503.html` | reserved for a future maintenance mode | no |
| `style.css`, images, fonts | referenced from the pages as `/fallback/<name>` | – |

Rules the service applies:

- Pages are served exactly as written, with the real status code (`404.html` goes out as a 404).
- Only `index.html` has placeholders, replaced by plain text substitution. If the database is unreachable they are replaced by nothing and the page still renders. The values are HTML-escaped.
- The Content Security Policy on these pages allows `<style>` blocks; scripts, images and fonts must be files in this directory (`/fallback/logo.svg`), never remote.
- Assets are served only for bare filenames with these extensions: `.css .js .png .jpg .jpeg .gif .svg .webp .ico .woff .woff2`, directly inside the directory. Subdirectories, symlinks pointing elsewhere and the page files themselves are not served under `/fallback/`.
- A missing or unreadable page falls back to the built-in behaviour; nothing here can break the service.

The directory is deliberately **not** part of any repository: it is server
content, owned by whoever has shell access. Keep your own copy under version
control or configuration management if you want its history.
