import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import docsVersionData from './docs-version.json';

// Единый источник истины для версии пакета, которую описывает документация.
// Должен совпадать с версией `giga-agent` в PyPI; проверяется в CI
// (.github/workflows/check-docs-version.yml).
const DOCS_VERSION = docsVersionData.version;

// Владелец и имя репозитория берутся из окружения GitHub Actions, поэтому
// сайт собирается с верными адресами и в форке, и в основном репозитории.
const [GH_OWNER, GH_REPO] = (
  process.env.GITHUB_REPOSITORY ?? 'trashchenkov/giga_agent'
).split('/');

const config: Config = {
  title: 'GigaAgent',
  tagline: 'Документация по универсальному AI-агенту на FastAPI, LangGraph и React',
  favicon: 'img/favicon.ico',

  customFields: {
    docsVersion: DOCS_VERSION,
  },

  future: {
    v4: true,
  },

  url: `https://${GH_OWNER}.github.io`,
  baseUrl: '/docs/',
  organizationName: GH_OWNER,
  projectName: GH_REPO,

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'ru',
    locales: ['ru', 'en'],
    localeConfigs: {
      ru: {label: 'Русский', htmlLang: 'ru'},
      en: {label: 'English', htmlLang: 'en'},
    },
  },

  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: `https://github.com/${GH_OWNER}/${GH_REPO}/tree/main/docs-site/`,
          lastVersion: '0.1.9',
          versions: {
            current: {
              label: 'main',
              path: 'next',
              banner: 'unreleased',
            },
            '0.1.9': {
              label: '0.1.9 (PyPI)',
              banner: 'none',
            },
          },
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/giga-agent-icon.png',
    announcementBar: {
      id: `docs-version-${DOCS_VERSION}`,
      content: `По умолчанию открыта стабильная документация <b>giga-agent ${DOCS_VERSION}</b> из PyPI. Актуальная документация репозитория доступна через переключатель версий.`,
      backgroundColor: '#1f2937',
      textColor: '#ffffff',
      isCloseable: true,
    },
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'GigaAgent',
      logo: {
        alt: 'GigaAgent',
        src: 'img/giga-agent-icon.png',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          position: 'left',
          label: 'Документация',
        },
        {to: '/quickstart/local', label: 'Быстрый старт', position: 'left'},
        {to: '/user-guide/chat', label: 'Пользователю', position: 'left'},
        {to: '/developer/architecture', label: 'Разработчикам', position: 'left'},
        {to: '/operations/configuration', label: 'Эксплуатация', position: 'left'},
        {
          type: 'docsVersionDropdown',
          position: 'right',
          dropdownActiveClassDisabled: true,
        },
        {type: 'localeDropdown', position: 'right'},
        {
          href: `https://github.com/${GH_OWNER}/${GH_REPO}`,
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Документация',
          items: [
            {label: 'Обзор', to: '/'},
            {label: 'Быстрый старт', to: '/quickstart/local'},
            {label: 'Руководство пользователя', to: '/user-guide/chat'},
          ],
        },
        {
          title: 'Разработчикам',
          items: [
            {label: 'Архитектура', to: '/developer/architecture'},
            {label: 'Расширение', to: '/developer/extending'},
          ],
        },
        {
          title: 'Эксплуатация',
          items: [
            {label: 'Конфигурация', to: '/operations/configuration'},
            {label: 'Sandbox и безопасность', to: '/operations/sandbox-security'},
            {label: 'Troubleshooting', to: '/operations/troubleshooting'},
          ],
        },
        {
          title: 'Проект',
          items: [
            {label: 'GitHub', href: `https://github.com/${GH_OWNER}/${GH_REPO}`},
          ],
        },
      ],
      copyright: `© ${new Date().getFullYear()} GigaAgent contributors. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
