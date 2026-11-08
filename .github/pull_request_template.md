## Summary

<!-- What changed and why? Reference any related issue (e.g. Fixes #12). -->

## Checklist

- [ ] Python, web portal, and C++17 firmware tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] User-facing text added or changed in **both** `es.json` and `en.json` with matching `{placeholders}` (desktop and/or web portal)
- [ ] Any new or updated LCD screen lines fit in **16 characters** in both Spanish and English
- [ ] Database changes (if any): SQLite upgrades existing databases cleanly, and Supabase migrations use a new numbered file that is safe to run twice and covered by Row-Level Security tests
- [ ] Documentation updated if hardware pins, `.env` keys, School Settings, or workflows changed
- [ ] Contains **no** real school/student/guardian data, `.db` files, or `.env` secrets
