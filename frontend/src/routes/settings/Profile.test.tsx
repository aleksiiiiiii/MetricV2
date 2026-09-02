import { QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import type { ProfileView } from '@/features/assistant/api';
import { createQueryClient } from '@/lib/query';

import { Profile } from './Profile';

/**
 * Section « Ce que je suis ».
 *
 * Ce que ces tests portent, et qu'aucun test d'API ne verrait : qu'un champ vide **reste**
 * vide au lieu de recevoir un défaut, et que ce qui part au modèle est montré.
 */

/** Les matériels, tels que le serveur les sert — l'écran n'en tient aucune copie. */
const CATALOGUE = [
  { value: 'body weight', common: true },
  { value: 'dumbbell', common: true },
  { value: 'barbell', common: true },
  { value: 'leverage machine', common: false },
  { value: 'smith machine', common: false },
];

const FILLED: ProfileView = {
  height_cm: 178,
  birth_year: 1995,
  training_days: 'lundi, mercredi, samedi',
  equipment: ['dumbbell'],
  equipment_unknown: [],
  equipment_catalogue: CATALOGUE,
  preferences: '',
  constraints: '',
  age: 31,
  lines: [
    'Taille : 178 cm',
    'Âge : 31 ans',
    'Jours où je peux m’entraîner : lundi, mercredi, samedi',
    'Matériel dont je dispose : dumbbell',
  ],
  token: 'jeton-reglages',
};

const EMPTY: ProfileView = {
  height_cm: null,
  birth_year: null,
  training_days: '',
  equipment: [],
  equipment_unknown: [],
  equipment_catalogue: CATALOGUE,
  preferences: '',
  constraints: '',
  age: null,
  lines: [],
  token: 'jeton-reglages',
};

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function stub(view: ProfileView = FILLED) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: input as string, init });
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(view),
      } as Response);
    }),
  );
}

function renderSection() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <Toaster>
        <Profile />
      </Toaster>
    </QueryClientProvider>,
  );
}

function writes(): Call[] {
  return calls.filter((call) => (call.init?.method ?? 'GET') !== 'GET');
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('profil', () => {
  it('montre ce qui part réellement à l’assistant', async () => {
    // Même parti pris que le condensé publié sous une réponse : la promesse se vérifie à
    // l'écran au lieu de rester déclarative dans un commentaire.
    stub();
    renderSection();

    expect(await screen.findByText('Taille : 178 cm')).toBeInTheDocument();
    expect(screen.getByText('Âge : 31 ans')).toBeInTheDocument();
  });

  it('laisse un profil vide vide, sans valeur par défaut', async () => {
    // La différence avec les objectifs juste au-dessus : un poids cible non réglé retombe
    // sur un repli parce qu'un objectif doit exister. Une taille non saisie n'en a pas —
    // afficher « 175 cm » parce que c'est courant serait une valeur inventée, et le modèle
    // en déduirait des charges.
    stub(EMPTY);
    renderSection();

    expect(await screen.findByLabelText('Taille (cm)')).toHaveValue('');
    expect(screen.getByText(/Rien pour l’instant/)).toBeInTheDocument();
  });

  it('n’envoie rien tant que rien n’a changé', async () => {
    stub();
    renderSection();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Enregistrer le profil' })).toBeDisabled();
    });
    expect(writes()).toHaveLength(0);
  });

  it('enregistre en PUT, avec la garde anti-conflit', async () => {
    // `PUT` et non `PATCH` : vider un champ est un geste normal sur un formulaire qu'on
    // voit en entier, et « absent = inchangé » le rendrait impossible.
    const user = userEvent.setup();
    stub();
    renderSection();

    const field = await screen.findByLabelText('Contraintes à respecter');
    await user.type(field, 'épaule droite sensible');
    await user.click(screen.getByRole('button', { name: 'Enregistrer le profil' }));

    await waitFor(() => {
      const call = writes()[0];
      expect(call?.init?.method).toBe('PUT');
      expect(call?.init?.headers).toMatchObject({ 'If-Match': 'jeton-reglages' });
      expect(JSON.parse(call?.init?.body as string)).toMatchObject({
        constraints: 'épaule droite sensible',
      });
    });
  });

  it('coche un matériel et l’envoie dans l’ordre du serveur', async () => {
    // L'ordre est celui du catalogue et non celui des appuis : deux enregistrements
    // successifs doivent produire la même ligne de consigne.
    const user = userEvent.setup();
    stub();
    renderSection();

    await user.click(await screen.findByRole('button', { name: 'barbell' }));
    await user.click(screen.getByRole('button', { name: 'body weight' }));
    await user.click(screen.getByRole('button', { name: 'Enregistrer le profil' }));

    await waitFor(() => {
      expect(JSON.parse(writes()[0]?.init?.body as string)).toMatchObject({
        equipment: ['body weight', 'dumbbell', 'barbell'],
      });
    });
  });

  it('garde les deux pastilles cochées coup sur coup', async () => {
    // Le défaut trouvé en pilotant l'écran : les deux appuis lisaient le même état figé et
    // la seconde pastille écrasait la première. Les tests précédents ne le voyaient pas —
    // `userEvent` sépare ses clics par un rendu, ce qui masque exactement le cas.
    stub();
    renderSection();

    const first = await screen.findByRole('button', { name: 'barbell' });
    const second = screen.getByRole('button', { name: 'body weight' });

    // Deux clics dans le **même** tour, comme deux appuis rapides du pouce.
    act(() => {
      first.click();
      second.click();
    });

    expect(first).toHaveAttribute('aria-pressed', 'true');
    expect(second).toHaveAttribute('aria-pressed', 'true');
  });

  it('range le matériel rare derrière un dépliant', async () => {
    // Douze cases se parcourent, vingt-huit poussent hors de vue les trois qu'on possède.
    const user = userEvent.setup();
    stub();
    renderSection();

    expect(await screen.findByRole('button', { name: 'dumbbell' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'smith machine' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Tout le matériel (2 de plus)' }));

    expect(screen.getByRole('button', { name: 'smith machine' })).toBeInTheDocument();
  });

  it('montre un matériel coché même s’il est rangé derrière le dépliant', async () => {
    // Le replier sous un dépliant fermé ferait croire qu'il a été décoché.
    stub({ ...FILLED, equipment: ['smith machine'] });
    renderSection();

    expect(await screen.findByRole('button', { name: 'smith machine' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('montre ce que le catalogue ne reconnaît pas, au lieu de le jeter', async () => {
    // Le champ était libre : une cellule existante porte une phrase. La faire disparaître
    // au premier affichage serait l'invariant « aucune valeur inventée » dans l'autre sens.
    stub({ ...FILLED, equipment_unknown: ['dumbbels 10kg et tapis'] });
    renderSection();

    expect(await screen.findByText(/dumbbels 10kg et tapis/)).toBeInTheDocument();
  });

  it('envoie null pour un champ vidé plutôt que de l’omettre', async () => {
    // « Je n'ai plus de rack » doit pouvoir s'écrire. Un champ omis serait conservé, et le
    // modèle continuerait de compter sur du matériel qui n'existe plus.
    const user = userEvent.setup();
    stub();
    renderSection();

    await user.clear(await screen.findByLabelText('Taille (cm)'));
    await user.click(screen.getByRole('button', { name: 'Enregistrer le profil' }));

    await waitFor(() => {
      const body = JSON.parse(writes()[0]?.init?.body as string) as Record<string, unknown>;
      expect(body.height_cm).toBeNull();
    });
  });
});
