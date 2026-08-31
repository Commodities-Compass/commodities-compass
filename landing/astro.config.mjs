// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import mdx from '@astrojs/mdx';
import tailwindcss from '@tailwindcss/vite';

/**
 * Wrap every Markdown `<table>` in `<div class="table-scroll">`.
 *
 * The legal pages carry wide tables (retention durations, sub-processors,
 * transfer guarantees). Without a scroll container they force the whole page
 * to scroll sideways on a phone, which on a page nobody can opt out of
 * reading is a real accessibility problem — and the first thing a reviewer
 * opens is the phone view.
 *
 * Written inline and dependency-free: it is a dozen lines of tree walk, and
 * a legal page should not gain an npm dependency to render a table.
 */
function rehypeWrapTables() {
  /** @param {any} tree */
  return (tree) => {
    /** @param {any} node */
    const walk = (node) => {
      if (!Array.isArray(node.children)) return;
      node.children = node.children.map((/** @type {any} */ child) => {
        walk(child);
        if (child.type === 'element' && child.tagName === 'table') {
          return {
            type: 'element',
            tagName: 'div',
            properties: { className: ['table-scroll'] },
            children: [child],
          };
        }
        return child;
      });
    };
    walk(tree);
  };
}

// https://astro.build/config
export default defineConfig({
  markdown: {
    rehypePlugins: [rehypeWrapTables],
  },
  // The standalone /disclaimer/ page is retired — it said, less completely,
  // what /mentions-legales/ now says, and two documents on the same subject
  // is a contradiction offered to whoever looks for one. Redirected rather
  // than deleted: the URL has been live and indexed since 2026.
  redirects: {
    '/disclaimer/': '/mentions-legales/',
    '/en/disclaimer/': '/en/legal-notice/',
  },
  site: 'https://com-compass.com',
  // GCS website config auto-redirects /en → /en/index.html when there is no
  // exact file match. Using 'always' aligns Astro's emitted URLs and canonical
  // tags with GCS's serving pattern so users see /en/ (clean) instead of the
  // ugly /en/index.html in the address bar after a redirect.
  trailingSlash: 'always',
  i18n: {
    defaultLocale: 'fr',
    locales: ['fr', 'en'],
    routing: {
      prefixDefaultLocale: false,
      redirectToDefaultLocale: false,
    },
  },
  integrations: [
    mdx(),
    sitemap({
      i18n: {
        defaultLocale: 'fr',
        locales: {
          fr: 'fr-FR',
          en: 'en-US',
        },
      },
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
  build: {
    inlineStylesheets: 'auto',
  },
});
