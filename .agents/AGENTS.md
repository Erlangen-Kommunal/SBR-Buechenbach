# Project Rules (SBR-Buechenbach)

## Version Bump on Push
- Bei jedem Push / Release im Projekt muss die Version (`APP_VERSION` & `CONTENT_VERSION` in `web/app.js` sowie `?v=...` Cache-Buster in `web/index.html`) automatisch um 1 erhöht werden.
