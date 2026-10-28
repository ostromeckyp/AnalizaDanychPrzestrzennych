import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Vitest bez `globals` nie sprząta DOM automatycznie.
afterEach(cleanup);
