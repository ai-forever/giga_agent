### Правила разработки
- Для обращения к API giga_agent используй `import { apiClient } from "@/lib/api-client";`. Base URL начинается с /api/
- При `vite build` предупреждение вида ``<script src="./app-config.js"> ... can't be bundled without type="module" attribute`` нужно игнорировать: `app-config.js` является runtime-конфигом и должен оставаться отдельным не-bundled скриптом.