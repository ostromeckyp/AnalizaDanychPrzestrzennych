// @vitest-environment node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript';
import { expect, it } from 'vitest';

// Te same opcje co CLI w `npm run gen:api` (domyślne), więc wynik jest bajt w bajt taki sam.
it('wygenerowany schemat API zgadza się z backend/openapi.json', async () => {
  const spec = resolve(__dirname, '../../../backend/openapi.json');
  const ast = await openapiTS(pathToFileURL(spec), { silent: true });
  const expected = `${COMMENT_HEADER}${astToString(ast)}`;
  const actual = readFileSync(resolve(__dirname, 'schema.ts'), 'utf8');
  expect(actual).toBe(expected);
});
