import React from 'react';
import {useBaseUrlUtils} from '@docusaurus/useBaseUrl';
import './ScreenshotCarousel.css';

type ScreenshotItem = {
  src: string;
  title: string;
  caption?: string;
};

type ScreenshotCarouselProps = {
  items: ScreenshotItem[];
  note?: string;
};

const defaultNote =
  'Скриншоты в галерее взяты из исторических прогонов GigaAgent и используются как иллюстрация сценария. Текущий интерфейс и точный вывод могут отличаться.';

export default function ScreenshotCarousel({items, note = defaultNote}: ScreenshotCarouselProps) {
  const {withBaseUrl} = useBaseUrlUtils();

  if (!items.length) {
    return null;
  }

  return (
    <section className="screenshotCarousel" aria-label="Галерея исторических прогонов">
      <p className="screenshotCarousel__note">{note}</p>
      <div className="screenshotCarousel__track">
        {items.map((item) => {
          const src = withBaseUrl(item.src);

          return (
            <figure className="screenshotCarousel__card" key={item.src}>
              <a href={src} target="_blank" rel="noreferrer">
                <img src={src} alt={item.title} loading="lazy" />
              </a>
              <figcaption>
                <strong>{item.title}</strong>
                {item.caption ? <span>{item.caption}</span> : null}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </section>
  );
}
