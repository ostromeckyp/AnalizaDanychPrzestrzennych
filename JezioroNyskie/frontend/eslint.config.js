import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

// Warstwy (spec §3): widok nie zna TanStack Query, klienta API ani fetch.
const viewLayerRules = {
  'no-restricted-imports': [
    'error',
    {
      patterns: [
        { group: ['@tanstack/react-query'], message: 'Zapytania tylko w src/vm/**.' },
        { group: ['**/api/**', '**/api'], message: 'Klient API tylko w src/vm/**.' },
      ],
    },
  ],
  'no-restricted-globals': ['error', { name: 'fetch', message: 'fetch tylko w src/api/**.' }],
  'no-restricted-properties': [
    'error',
    { object: 'window', property: 'fetch', message: 'fetch tylko w src/api/**.' },
    { object: 'globalThis', property: 'fetch', message: 'fetch tylko w src/api/**.' },
  ],
};

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/api/schema.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { 'react-hooks': reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  { files: ['src/components/**', 'src/pages/**'], ignores: ['**/*.test.*'], rules: viewLayerRules },
);
