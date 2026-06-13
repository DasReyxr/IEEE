import eventsFile from '../content/events/events.md';
import ev1 from '../assets/AI_Flyer.png';
import tp2 from '../assets/TP_2.jpg';
import { placeholderDataUrl } from './placeholders';

const IMAGE_MAP = {
  'AI_Flyer.png': ev1,
  'TP_2.jpg': tp2,
};

let cachedEvents = null;
let pending = null;
const PUBLIC_URL = process.env.PUBLIC_URL || '';

function parseEvents(text) {
  const chunks = text
    .split('<!-- EVENT -->')
    .map((chunk) => chunk.trim())
    .filter(Boolean);

  return chunks
    .map((chunk) => {
      const { data, content } = parseFrontmatter(chunk);
      // Replace image paths that start with '/' to include PUBLIC_URL so
      // they resolve correctly both in dev server and on GitHub Pages.
          // Normalize image links to point to PUBLIC_URL so images placed in `public/` load
          // Works for links like `/TP_Omar.jpg` or `TP_Omar.jpg` in Markdown.
          const pub = PUBLIC_URL;
          const fixedContent = content.replace(/(!\[[^\]]*\]\()([^\)]+)\)/g, (m, prefix, path) => {
            const trimmed = path.trim();
            if (/^https?:\/\//i.test(trimmed)) return m; // external links unchanged
            // remove any surrounding <> if present
            const unwrapped = trimmed.replace(/^<|>$/g, '');
            // if path already contains PUBLIC_URL, leave it
            if (pub && unwrapped.startsWith(pub)) return m;
            // build a normalized URL pointing to public folder
            const pathNoLeading = unwrapped.replace(/^\//, '');
            const normalized = pub ? `${pub}/${pathNoLeading}` : `/${pathNoLeading}`;
            return `${prefix}${normalized})`;
          });

      return {
        ...data,
        body: fixedContent.trim(),
      };
    })
    .filter((event) => event.slug);
}

function parseFrontmatter(chunk) {
  const match = chunk.match(/^---\s*([\s\S]*?)\s*---\s*([\s\S]*)$/);
  if (!match) {
    return { data: {}, content: chunk };
  }

  const raw = match[1];
  const content = match[2] || '';
  const data = {};

  raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const idx = line.indexOf(':');
      if (idx === -1) {
        return;
      }

      const key = line.slice(0, idx).trim();
      let value = line.slice(idx + 1).trim();

      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }

      data[key] = value;
    });

  return { data, content };
}

export async function loadEvents() {
  if (cachedEvents) {
    return cachedEvents;
  }

  if (pending) {
    return pending;
  }

  pending = fetch(eventsFile)
    .then((response) => response.text())
    .then((text) => {
      const events = parseEvents(text)
        .map((event) => {
          // Prefer bundled assets if present in IMAGE_MAP, otherwise fallback to public/events
          let imageSrc = null;
          if (event.image && IMAGE_MAP[event.image]) {
            imageSrc = IMAGE_MAP[event.image];
          } else if (event.image) {
            const pathNoLeading = event.image.replace(/^\//, '').replace(/^events\//, '');
            imageSrc = PUBLIC_URL ? `${PUBLIC_URL}/events/${pathNoLeading}` : `/events/${pathNoLeading}`;
          } else {
            imageSrc = placeholderDataUrl(event.title, event.accent);
          }

          return {
            ...event,
            imageSrc: imageSrc || placeholderDataUrl(event.title, event.accent),
          };
        })
        .sort((a, b) => new Date(b.dateISO) - new Date(a.dateISO));

      cachedEvents = events;
      pending = null;
      return events;
    });

  return pending;
}
