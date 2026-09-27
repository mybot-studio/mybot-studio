import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// authFetch reads the token/language from Web Storage, which Node does not
// provide; every scenario below installs its own values over this stub.
const store = new Map();
Object.defineProperty(globalThis, 'localStorage', {
  value: {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  },
  configurable: true,
});
const unauthorized = [];
Object.defineProperty(globalThis, 'window', {
  value: { dispatchEvent: (event) => unauthorized.push(event.type ?? event) },
  configurable: true,
});

const { api } = await import('./api.js');

test('API errors preserve backend detail rather than swallowing it in the JSON catch', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Specific backend diagnostic' }), { status: 400, headers: { 'Content-Type': 'application/json' } });
  try { await assert.rejects(api.getBots(), /Specific backend diagnostic/); }
  finally { globalThis.fetch = original; }
});

test('every request carries the bearer token and the selected language', async () => {
  const original = globalThis.fetch;
  store.set('mybot_token', 'jwt-value');
  store.set('mybot_lang', 'ru');
  let seen = null;
  globalThis.fetch = async (url, options = {}) => {
    seen = options.headers;
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    await api.getBots();
    const headers = seen;
    assert.equal(headers.get('Authorization'), 'Bearer jwt-value');
    assert.equal(headers.get('Accept-Language'), 'ru');
  } finally {
    globalThis.fetch = original;
    store.delete('mybot_token');
    store.delete('mybot_lang');
  }
});

test('an expired token is dropped and the session is ended once', async () => {
  const original = globalThis.fetch;
  store.set('mybot_token', 'expired-jwt');
  globalThis.fetch = async () => new Response('{"detail":"expired"}', { status: 401, headers: { 'Content-Type': 'application/json' } });
  try {
    await assert.rejects(api.getBots());
    assert.equal(store.has('mybot_token'), false);
    assert.deepEqual(unauthorized.slice(-1), ['mybot:unauthorized']);
  } finally {
    globalThis.fetch = original;
    store.delete('mybot_token');
  }
});

test('token and language keys match the keys the UI actually writes', () => {
  const read = (relative) => readFileSync(new URL(relative, import.meta.url), 'utf8');
  const keys = [...read('./api.js').matchAll(/(?:TOKEN_KEY|LANG_KEY) = '([^']*)'/g)].map((match) => match[1]);
  assert.equal(keys.length, 2, 'api.js must define exactly a token key and a language key');
  const [tokenKey, languageKey] = keys;
  assert.ok(tokenKey && languageKey, 'storage keys must not be empty or redacted placeholders');
  assert.ok(read('../components/Auth/LoginPage.jsx').includes(`setItem('${tokenKey}'`),
    'LoginPage has to store the token under the key authFetch reads');
  assert.ok(read('../locales/i18n.jsx').includes(`'${languageKey}'`),
    'the language provider has to persist the language under the key authFetch reads');
});

test('API fallback errors follow the selected locale', async () => {
  const original = globalThis.fetch;
  const storage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => 'fa' }, configurable: true });
  globalThis.fetch = async () => new Response('{}', { status: 503, headers: { 'Content-Type': 'application/json' } });
  try { await assert.rejects(api.getBots(), /ربات/); }
  finally {
    globalThis.fetch = original;
    if (storage) Object.defineProperty(globalThis, 'localStorage', storage); else delete globalThis.localStorage;
  }
});
