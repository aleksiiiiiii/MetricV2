import { describe, expect, it } from 'vitest';

import {
  delta,
  duration,
  hoursMinutes,
  isoDay,
  num,
  pace,
  paceOf,
  percent,
  volume,
} from './format';

describe('nombres', () => {
  it('utilise la virgule décimale française', () => {
    expect(num(68.4)).toBe('68,4');
  });

  it('supprime les décimales inutiles', () => {
    expect(num(68)).toBe('68');
  });

  it('signe un écart avec un vrai signe moins typographique', () => {
    // U+2212 et non un trait d'union : il s'aligne sur le plus et sur les chiffres
    // à chasse fixe.
    expect(delta(-0.4)).toBe('−0,4');
    expect(delta(1.2)).toBe('+1,2');
  });

  it('formate un pourcentage', () => {
    expect(percent(0.81)).toBe('81 %');
  });
});

describe('durées', () => {
  it('reste en mm:ss sous une heure', () => {
    expect(duration(44.2)).toBe('44:12');
  });

  it('passe à h:mm:ss au-delà', () => {
    expect(duration(78.733)).toBe('1:18:44');
  });

  it('complète les secondes à deux chiffres', () => {
    expect(duration(5.05)).toBe('5:03');
  });

  it('exprime le sommeil en heures et minutes', () => {
    expect(hoursMinutes(440)).toBe('7 h 20');
    expect(hoursMinutes(120)).toBe('2 h');
    expect(hoursMinutes(45)).toBe('45 min');
  });
});

describe('allure', () => {
  it("dérive l'allure d'une distance et d'une durée", () => {
    expect(paceOf(8.4, 44.2)).toBe('5:16');
  });

  it('rend null quand elle est indéterminable', () => {
    expect(paceOf(0, 44)).toBeNull();
    expect(paceOf(8.4, 0)).toBeNull();
  });

  it('formate une allure déjà calculée', () => {
    expect(pace(5.2)).toBe('5:12');
  });
});

describe('volumes', () => {
  it('reste en millilitres sous le litre', () => {
    expect(volume(500)).toBe('500 ml');
  });

  it('passe en litres au-delà', () => {
    expect(volume(2000)).toBe('2 L');
    expect(volume(1500)).toBe('1,5 L');
  });
});

describe('dates', () => {
  it('sérialise en heure locale et non en UTC', () => {
    // Le piège que `toISOString()` tend : le 26 juillet à 1 h à Paris est encore le
    // 25 en UTC, et la journée serait rattachée au mauvais jour (`HEAT-32`).
    const minuitPasse = new Date(2026, 6, 26, 1, 0, 0);

    expect(isoDay(minuitPasse)).toBe('2026-07-26');
  });
});
