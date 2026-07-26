import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Health } from '@/lib/health';

import { Home } from './Home';

const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  environment: 'test',
  time: '2026-07-26T11:02:00+02:00',
  timezone: 'Europe/Paris',
  storage_configured: false,
  ai_enabled: false,
};

function renderHome() {
  return render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Home', () => {
  it('affiche l’état du service quand l’API répond', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(HEALTH),
      } satisfies Partial<Response>),
    );

    renderHome();

    expect(await screen.findByText('en ligne')).toBeInTheDocument();
    expect(screen.getByText('Europe/Paris')).toBeInTheDocument();
  });

  it("annonce une dégradation propre quand l'IA et le stockage sont absents (IA-07)", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(HEALTH),
      } satisfies Partial<Response>),
    );

    renderHome();

    expect(await screen.findByText('saisie manuelle')).toBeInTheDocument();
    expect(screen.getByText('non configuré')).toBeInTheDocument();
  });

  it('signale une API injoignable sans écran blanc', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connexion refusée')));

    renderHome();

    expect(await screen.findByText('API injoignable')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Metric' })).toBeInTheDocument();
  });
});
