interface RuntimeSttConfig {
  enabled: boolean;
  runtime: "salute" | null;
}

interface RuntimeConfig {
  baseUrl?: string;
  basePath?: string;
  apiBasePath?: string;
  apiAgentBasePath?: string;
  runtimeLocal?: boolean;
  skipOnboarding?: boolean;
  stt?: RuntimeSttConfig;
}

declare global {
  interface Window {
    __GIGA_AGENT_CONFIG__?: RuntimeConfig;
  }
}

export const runtimeConfig: RuntimeConfig =
  typeof window !== "undefined" ? (window.__GIGA_AGENT_CONFIG__ ?? {}) : {};

function normalizeBasePath(value: string | undefined): string {
  if (!value) {
    return "/";
  }

  const trimmed = value.trim();
  if (!trimmed || trimmed === "/") {
    return "/";
  }

  return `/${trimmed.replace(/^\/+|\/+$/g, "")}`;
}

function normalizeAbsoluteBaseUrl(value: string | undefined): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    const normalizedPath = parsed.pathname.replace(/\/+$/, "");
    return `${parsed.origin}${normalizedPath}`;
  } catch {
    return null;
  }
}

function toTrailingSlashPath(value: string): string {
  return value === "/" ? "/" : `${value}/`;
}

function joinBasePath(basePath: string, suffix: string): string {
  const normalizedBasePath = normalizeBasePath(basePath);
  const normalizedSuffix = suffix.replace(/^\/+/, "");
  if (!normalizedSuffix) {
    return normalizedBasePath;
  }
  if (normalizedBasePath === "/") {
    return `/${normalizedSuffix}`;
  }
  return `${normalizedBasePath}/${normalizedSuffix}`;
}

const configuredBaseUrl = normalizeAbsoluteBaseUrl(runtimeConfig.baseUrl);
const configuredBasePath = normalizeBasePath(
  runtimeConfig.basePath ??
    (configuredBaseUrl ? new URL(configuredBaseUrl).pathname : "/"),
);

export const UI_BASENAME = configuredBasePath === "/" ? "" : configuredBasePath;
export const APP_BASE_PATH = configuredBasePath;
export const APP_ROOT_PATH = toTrailingSlashPath(APP_BASE_PATH);
export const APP_BASE_URL =
  configuredBaseUrl ??
  new URL(toTrailingSlashPath(APP_BASE_PATH), window.location.origin)
    .toString()
    .replace(/\/$/, "");

const configuredApiBasePath = runtimeConfig.apiBasePath
  ? normalizeBasePath(runtimeConfig.apiBasePath)
  : joinBasePath(APP_BASE_PATH, "api");

const configuredApiBaseUrl = normalizeAbsoluteBaseUrl(
  configuredBaseUrl
    ? new URL("api/", `${APP_BASE_URL}/`).toString()
    : new URL(
        toTrailingSlashPath(configuredApiBasePath),
        window.location.origin,
      ).toString(),
);

export const API_BASE_URL =
  configuredApiBaseUrl ?? `${window.location.origin}/api`;
export const API_PREFIX = API_BASE_URL;
export const API_AGENT_PREFIX = `${API_BASE_URL}/agent`;
export const RUNTIME_LOCAL = runtimeConfig.runtimeLocal === true;
export const SKIP_ONBOARDING = runtimeConfig.skipOnboarding === true;
export const BACKEND_STT_ENABLED = runtimeConfig.stt?.enabled === true;

export const TOOL_MAP = {
  lean_canvas: "Агент по созданию Lean Canvas",
  python: "Код-интерпретатор",
  search: "Поиск",
  shell: "Командная строка",
  vk_get_posts: "Получение постов (ВК)",
  ask_about_image: "Анализ изображения",
  vk_get_comments: "Получение комментариев к посту (ВК)",
  vk_get_last_comments: "Получение последних комментариев (ВК)",
  get_workflow_runs: "Получение CI Runs (GitHub)",
  get_cve_for_package: "Получение CVE для пакета",
  get_pull_request: "Получение PR (GitHub)",
  list_pull_requests: "Получение списка PR (GitHub)",
  weather: "Получение погоды",
  create_landing: "Создание веб-страницы",
  podcast_generate: "Генерация подкаста",
  debates: "Дебаты агентов",
  generate_presentation: "Генерация презентации",
  create_meme: "Агент Мемов",
  get_urls: "Скачивание ссылок",
  city_explore: "Исследователь города",
  gen_image: "Генерация изображения",
  browser_task: "Агент Б.Раузер",
  get_documents: "Поиск по базе знаний",
  researcher_agent: "Исследовательский агент",
};

export const PROGRESS_AGENTS = {
  lean_canvas: {
    "1_customer_segments": "Определяет целевых клиентов",
    "2_problem": "Определяет проблему",
    "3_unique_value_proposition": "Определяет уникальное предложение",
    "3.1_check_unique": "Определяет уникальное предложение",
    "4_solution": "Предлагает решение проблем",
    "5_channels": "Находит каналы привлечения",
    "6_revenue_streams": "Планирует заработок",
    "7_cost_structure": "Определяет затраты",
    "8_key_metrics": "Определяет ключевые метрики",
    "9_unfair_advantage": "Находит преимущество",
    get_feedback: "Находит преимущество",
  },
  create_landing: {
    plan: "Создание плана страницы",
    image: "Генерация изображений",
    coder: "Создание кода страницы",
  },
  podcast_generate: {
    __start__: "Скачивание контента страницы",
    download: "Анализ переписки",
    summarize_messages: "Генерация сюжета подкаста",
    script: "Генерация аудио",
    audio_gen: "Генерация аудио",
  },
  generate_presentation: {
    __start__: "Создание плана",
    plan_node: "Генерация изображений",
    image: "Генерация слайдов",
    slides_node: "Генерация слайдов",
  },
  create_meme: {
    __start__: "Генерация идеи",
    text: "Генерация изображения",
    image: "Генерация изображения",
  },
  city_explore: {
    __start__: "Поиск достопримечательностей",
    attractions_node: "Поиск отелей",
    hotels_node: "Поиск лучших ресторанов / кафе",
    food_node: "Поиск лучших ресторанов / кафе",
  },
  researcher_agent: {
    __start__: "Начинает исследование",
    research_agent: "Проводит глубокое исследование",
    critique_agent: "Анализирует результаты",
  },
};

export const BROWSER_USE_NAME = "browser_task";

export const TIME_TO_NEXT_TASK = 15;

export const MCP_PROXY_URL: string | undefined = import.meta.env
  ?.VITE_MCP_PROXY_URL;

export const ragEnabled = () => {
  // TODO: Здесь нужно подтягивать информацию о текущем агенте и
  //  доступен ли в нем модуль rag
  return true;
};
