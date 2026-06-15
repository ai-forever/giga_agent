import { PromptSuggestionScenario } from "@/types/prompt-suggestions";

interface RuntimeSttConfig {
  enabled: boolean;
  runtime: "salute" | null;
}

interface RuntimePromptSuggestionsConfig {
  enabled?: boolean;
  starterEnabled?: boolean;
  recommendationsEnabled?: boolean;
  followUpEnabled?: boolean;
}

interface RuntimeConfig {
  baseUrl?: string;
  basePath?: string;
  apiBasePath?: string;
  apiAgentBasePath?: string;
  runtimeLocal?: boolean;
  skipOnboarding?: boolean;
  stt?: RuntimeSttConfig;
  promptSuggestions?: RuntimePromptSuggestionsConfig;
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
export const PROMPT_SUGGESTIONS_ENABLED =
  runtimeConfig.promptSuggestions?.enabled ?? true;
export const STARTER_PROMPT_SUGGESTIONS_ENABLED =
  runtimeConfig.promptSuggestions?.starterEnabled ?? true;
export const STARTER_RECOMMENDATIONS_ENABLED =
  runtimeConfig.promptSuggestions?.recommendationsEnabled ?? true;
export const FOLLOW_UP_PROMPT_SUGGESTIONS_ENABLED =
  runtimeConfig.promptSuggestions?.followUpEnabled ?? true;

export interface PromptTemplateTopic {
  id: string;
  label: string;
  prompts: PromptSuggestionScenario[];
}

export const PROMPT_TEMPLATE_TOPICS: PromptTemplateTopic[] = [
  {
    id: "data_code",
    label: "Анализ данных и код",
    prompts: [
      {
        title: "Анализ датасета",
        text: "Напиши Python-скрипт для анализа загруженного CSV-файла: найди аномалии, построй график распределения и выведи основные метрики",
        modules: { repl: true }
      },
      {
        title: "Создание тестовых данных",
        text: "Создай тестовый датасет для решения задачи классификации проблем пользователей из заявок техподдержки. Начни с 5 семплов",
        modules: { repl: true }
      },
      {
        title: "Работа с API и графики",
        text: "Напиши код, который запросит исторические данные о курсе валют через публичное API, проанализирует тренд и построит красивый график изменения цены",
        modules: { repl: true }
      },
    ],
  },
  {
    id: "content",
    label: "Создание контента",
    prompts: [
      {
        title: "Создание лендинга",
        text: "Сгенерируй лендинг для нового фитнес-приложения: продумай структуру из 4 блоков (Hero, Преимущества, Отзывы, CTA), напиши продающие тексты и создай HTML/Tailwind код",
        modules: { subagents_legacy: true },
      },
      {
        title: "Презентация продукта",
        text: "Сделай презентацию-дайджест по новостям в ИИ-сфере за последний месяц. Сгенерируй изображения для каждого слайда",
        modules: { subagents_legacy: true, image: true },
      },
      {
        title: "Подкаст и мемы",
        text: "Сгенерируй сценарий короткого подкаста про удаленную работу и сделай смешной мем на эту тему",
        modules: { subagents_legacy: true, image: true },
      },
    ],
  },
  {
    id: "research",
    label: "Исследования и поиск",
    prompts: [
      {
        title: "Глубокое исследование",
        text: "Найди статьи о подробностях архитектуры Deepseek-V4. Сделай выжимку и объясни простыми словами, добавляя иллюстрации к объяснениям. Оформи в виде отчета",
        deepResearchForced: true,
        modules: { search: true, scraper: true },
      },
      {
        title: "Анализ конкурентов",
        text: "Найди в интернете 3 главных конкурентов Notion, сравни их тарифные планы и ключевые фичи в виде таблицы",
        modules: { search: true, scraper: true },
      },
      {
        title: "Поиск по базе знаний",
        text: "Найди в базе знаний все документы, связанные с онбордингом новых сотрудников, и составь из них единый чеклист",
        ragMode: "all",
        modules: { rag: true },
      },
    ],
  },
  {
    id: "business",
    label: "Бизнес и продукты",
    prompts: [
      {
        title: "Бизнес-модель (Lean Canvas)",
        text: "Составь Lean Canvas для стартапа: сервис доставки еды по подписке для веганов. Опиши сегменты, проблему и решение",
        modules: { subagents_legacy: true },
      },
      {
        title: "Анализ рынка",
        text: "Проведи анализ рынка онлайн-образования: выдели основные тренды, барьеры для входа и потенциальные ниши",
        modules: { search: true, scraper: true },
      },
      {
        title: "Стратегия выхода на рынок",
        text: "Подготовь план запуска (Go-to-Market) для нового Telegram-бота по изучению английского: определи целевую аудиторию, выбери 3 канала привлечения и распиши шаги на первый месяц",
        modules: { search: true },
      },
    ],
  },
  {
    id: "integrations",
    label: "Интеграции",
    prompts: [
      {
        title: "Анализ GitHub PR",
        text: "Получи список последних Pull Requests в репозитории, проанализируй изменения и напиши краткий Changelog",
        modules: { github: true },
      },
      {
        title: "Анализ соцсетей",
        text: "Собери последние комментарии к популярному посту в VK, проанализируй тональность и выдели главные жалобы",
        modules: { vk: true },
      },
      {
        title: "Погода и планирование",
        text: "Узнай прогноз погоды в Москве на выходные и предложи 3 варианта активного отдыха на улице",
        modules: { weather: true },
      },
    ],
  },
];

export const STATIC_STARTER_RECOMMENDATIONS: PromptSuggestionScenario[] = [
  {
    title: "Глубокое исследование темы",
    text: "Запусти глубокое исследование (Deep Research) по теме 'Тренды AI в 2026 году': собери источники и сделай выжимку",
    deepResearchForced: true,
  },
  {
    title: "Создание лендинга",
    text: "Сгенерируй код лендинга для нового продукта, включая тексты и структуру страницы",
    skills: ["create_landing"],
  },
  {
    title: "Анализ данных (Python)",
    text: "Напиши и выполни Python-скрипт для генерации тестового датасета и построй по нему график",
    modules: { repl: true },
  },
  {
    title: "Бизнес-модель стартапа",
    text: "Составь Lean Canvas для нового мобильного приложения: опиши проблему, решение и целевую аудиторию",
    skills: ["lean_canvas"],
  },
  {
    title: "Анализ комментариев VK",
    text: "Собери последние комментарии из паблика VK и сделай саммари основных тем, которые обсуждают пользователи",
    modules: { vk: true },
  },
  {
    title: "Генерация презентации",
    text: "Создай презентацию на 5 слайдов с изображениями для питчинга нового проекта инвесторам",
    skills: ["generate_presentation"],
  },
  {
    title: "Анализ GitHub репозитория",
    text: "Получи информацию о последних Pull Requests в репозитории и составь список изменений (Changelog)",
    modules: { github: true },
  },
  {
    title: "Создание подкаста",
    text: "Напиши сценарий для короткого подкаста на тему 'Как нейросети меняют работу программистов'",
    skills: ["podcast_generate"],
  },
];

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
  run_deep_research: "Глубокое исследование",
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
  run_deep_research: {
    __start__: "Запускаю глубокое исследование",
    planner: "Раскладываю запрос на подвопросы",
    search: "Ищу источники в сети",
    read: "Читаю страницы и собираю выжимки",
    reflect: "Оцениваю, достаточно ли данных",
    compose: "Собираю финальный отчёт с цитатами",
    critique: "Редактор проверяет отчёт",
    finalize: "Сохраняю отчёт",
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
