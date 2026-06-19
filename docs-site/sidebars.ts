import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    'intro',
    {
      type: 'category',
      label: 'Быстрый старт',
      items: ['quickstart/local', 'quickstart/first-chat', 'quickstart/docker'],
    },
    {
      type: 'category',
      label: 'Примеры',
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
    {
      type: 'category',
      label: 'Руководство пользователя',
      items: [
        'user-guide/chat',
        'user-guide/projects',
        'user-guide/capabilities',
        'user-guide/files-and-artifacts',
        'user-guide/tools',
        'user-guide/rag',
        'user-guide/memory',
        'user-guide/images',
        'user-guide/external-services',
        'user-guide/mcp',
      ],
    },
    {
      type: 'category',
      label: 'Разработчикам',
      items: [
        'developer/architecture',
        'developer/runtime-resolver',
        'developer/modules',
        'developer/tools',
        'developer/subagents',
        'developer/extending',
      ],
    },
    {
      type: 'category',
      label: 'Эксплуатация',
      items: [
        'operations/configuration',
        'operations/sandbox-security',
        'operations/shared-server',
        'operations/troubleshooting',
      ],
    },
  ],
};

export default sidebars;
