import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import Translate, {translate} from '@docusaurus/Translate';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './index.module.css';

type Card = {
  to: string;
  title: ReactNode;
  description: ReactNode;
};

const cards: Card[] = [
  {
    to: '/docs/quickstart/local',
    title: <Translate id="homepage.card.quickstart.title">Быстрый старт</Translate>,
    description: (
      <Translate id="homepage.card.quickstart.description">
        Установка пакета, локальный запуск и первый вход в веб-интерфейс.
      </Translate>
    ),
  },
  {
    to: '/docs/quickstart/first-chat',
    title: <Translate id="homepage.card.firstChat.title">Первый чат</Translate>,
    description: (
      <Translate id="homepage.card.firstChat.description">
        Настройка коннектора, языковой модели и проверка первого сообщения.
      </Translate>
    ),
  },
  {
    to: '/docs/user-guide/capabilities',
    title: <Translate id="homepage.card.capabilities.title">Возможности</Translate>,
    description: (
      <Translate id="homepage.card.capabilities.description">
        Что работает сразу, а что требует провайдеров, секретов и прав.
      </Translate>
    ),
  },
  {
    to: '/docs/operations/configuration',
    title: <Translate id="homepage.card.operations.title">Эксплуатация</Translate>,
    description: (
      <Translate id="homepage.card.operations.description">
        Конфигурация, безопасность изолированной среды и совместный сервер.
      </Translate>
    ),
  },
];

export default function Home(): ReactNode {
  return (
    <Layout
      title={translate({id: 'homepage.title', message: 'GigaAgent Docs'})}
      description={translate({
        id: 'homepage.description',
        message: 'Документация GigaAgent 0.1.9',
      })}>
      <header className={clsx('hero hero--primary', styles.heroBanner)}>
        <div className="container">
          <img
            className={styles.heroLogo}
            src={useBaseUrl('/img/giga-agent-logo-on-dark.png')}
            alt="GigaAgent"
          />
          <Heading as="h1" className="hero__title">
            <Translate id="homepage.hero.title">Документация GigaAgent</Translate>
          </Heading>
          <p className="hero__subtitle">
            <Translate id="homepage.hero.subtitle">
              Практическое руководство по установке, первому запуску, настройке
              модели, возможностям агента и безопасному общему доступу.
            </Translate>
          </p>
          <div className={styles.buttons}>
            <Link className="button button--secondary button--lg" to="/docs/intro">
              <Translate id="homepage.hero.cta">Открыть документацию</Translate>
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
                    <Translate id="homepage.card.cta">Перейти</Translate>
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
