import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import styles from './index.module.css';

const cards = [
  {
    title: 'Быстрый старт',
    description: 'Установка пакета, локальный запуск и первый вход в веб-интерфейс.',
    to: '/docs/quickstart/local',
  },
  {
    title: 'Первый чат',
    description: 'Настройка коннектора, языковой модели и проверка первого сообщения.',
    to: '/docs/quickstart/first-chat',
  },
  {
    title: 'Возможности',
    description: 'Что работает сразу, а что требует провайдеров, секретов и прав.',
    to: '/docs/user-guide/capabilities',
  },
  {
    title: 'Эксплуатация',
    description: 'Конфигурация, безопасность изолированной среды и совместный сервер.',
    to: '/docs/operations/configuration',
  },
];

export default function Home(): ReactNode {
  return (
    <Layout
      title="GigaAgent Docs"
      description="Документация GigaAgent 0.1.9">
      <header className={clsx('hero hero--primary', styles.heroBanner)}>
        <div className="container">
          <Heading as="h1" className="hero__title">
            Документация GigaAgent
          </Heading>
          <p className="hero__subtitle">
            Практическое руководство по установке, первому запуску, настройке
            модели, возможностям агента и безопасному общему доступу.
          </p>
          <div className={styles.buttons}>
            <Link className="button button--secondary button--lg" to="/docs/intro">
              Открыть документацию
            </Link>
          </div>
        </div>
      </header>
      <main className="container margin-vert--lg">
        <div className="row">
          {cards.map((card) => (
            <div className="col col--3" key={card.to}>
              <div className="card margin-bottom--lg">
                <div className="card__body">
                  <Heading as="h3">{card.title}</Heading>
                  <p>{card.description}</p>
                </div>
                <div className="card__footer">
                  <Link className="button button--primary button--block" to={card.to}>
                    Перейти
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>
    </Layout>
  );
}
