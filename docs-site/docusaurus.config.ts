import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import docsVersionData from './docs-version.json';

// Единый источник истины для версии пакета, которую описывает документация.
// Должен совпадать с версией `giga-agent` в PyPI; проверяется в CI
// (.github/workflows/check-docs-version.yml).
const DOCS_VERSION = docsVersionData.version;

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

  url: 'https://trashchenkov.github.io',
  baseUrl: '/giga_agent/',
  organizationName: 'trashchenkov',
  projectName: 'giga_agent',

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'ru',
    locales: ['ru'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/trashchenkov/giga_agent/tree/main/docs-site/',
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
      content: `Эта документация соответствует пакету <b>giga-agent ${DOCS_VERSION}</b> из PyPI. Код в репозитории может уходить вперёд релиза.`,
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
        {to: '/docs/quickstart/local', label: 'Быстрый старт', position: 'left'},
        {to: '/docs/user-guide/chat', label: 'Пользователю', position: 'left'},
        {to: '/docs/developer/architecture', label: 'Разработчикам', position: 'left'},
        {to: '/docs/operations/configuration', label: 'Эксплуатация', position: 'left'},
        {
          href: 'https://github.com/trashchenkov/giga_agent',
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
            {label: 'Обзор', to: '/docs/intro'},
            {label: 'Быстрый старт', to: '/docs/quickstart/local'},
            {label: 'Руководство пользователя', to: '/docs/user-guide/chat'},
          ],
        },
        {
          title: 'Разработчикам',
          items: [
            {label: 'Архитектура', to: '/docs/developer/architecture'},
            {label: 'Расширение', to: '/docs/developer/extending'},
          ],
        },
        {
          title: 'Эксплуатация',
          items: [
            {label: 'Конфигурация', to: '/docs/operations/configuration'},
            {label: 'Sandbox и безопасность', to: '/docs/operations/sandbox-security'},
            {label: 'Troubleshooting', to: '/docs/operations/troubleshooting'},
          ],
        },
        {
          title: 'Проект',
          items: [
            {label: 'GitHub', href: 'https://github.com/trashchenkov/giga_agent'},
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
