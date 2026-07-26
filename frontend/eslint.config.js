import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'dev-dist', 'coverage', 'public/fonts', 'src/styles/fonts.css'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Le style est délégué à Prettier ; ESLint ne juge que la correction.
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/no-unnecessary-condition': 'off',
      // Une application de mesure interpole des nombres en permanence — distances,
      // volumes, séries, codes HTTP. Les convertir à la main n'apporterait rien.
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    rules: {
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',
    },
  },
  {
    files: ['scripts/**/*.mjs', 'vite.config.ts'],
    languageOptions: { globals: globals.node },
  },
);
