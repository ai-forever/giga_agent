import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// Категории раскрыты и не сворачиваются (`collapsible: false`), поэтому в
// сайдбаре они выглядят как заголовки-разделы, а не как складные группы.
const sidebars: SidebarsConfig = {
  docs: [
    'overview',
    {
      type: 'category',
      label: 'Быстрый старт',
      collapsible: false,
      collapsed: false,
      items: ['quickstart/local', 'quickstart/first-chat', 'quickstart/docker'],
    },
    {
      type: 'category',
      label: 'Руководство пользователя',
      collapsible: false,
      collapsed: false,
      items: [
        'user-guide/chat',
        'user-guide/projects',
        'user-guide/capabilities',
        'user-guide/files-and-artifacts',
        'user-guide/tools',
        'user-guide/connectors',
        'user-guide/yandex-services',
        'user-guide/widgets',
        'user-guide/scheduler',
        'user-guide/channels',
        'user-guide/rag',
        'user-guide/memory',
        'user-guide/images',
        'user-guide/external-services',
      ],
    },
    {
      type: 'category',
      label: 'Разработчикам',
      collapsible: false,
      collapsed: false,
      items: [
        'developer/architecture',
        'developer/runtime-resolver',
        'developer/modules',
        'developer/tools',
        'developer/integrations',
        'developer/genui',
        'developer/subagents',
        'developer/extending',
      ],
    },
    {
      type: 'category',
      label: 'Эксплуатация',
      collapsible: false,
      collapsed: false,
      items: [
        'operations/configuration',
        'operations/sandbox-security',
        'operations/shared-server',
        'operations/troubleshooting',
      ],
    },
    {
      type: 'category',
      label: 'Примеры',
      collapsible: false,
      collapsed: false,
      items: [
        'examples/index',
        'examples/data-analysis',
        'examples/vk-social-listening',
        'examples/business-analytics',
        'examples/presentations',
        'examples/image-to-business-canvas',
        'examples/security-logs',
      ],
    },
  ],
};

export default sidebars;
