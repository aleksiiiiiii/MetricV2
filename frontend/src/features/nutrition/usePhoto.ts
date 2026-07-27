/**
 * Chargement d'une photo de repas servie par un endpoint **authentifié** (`NUT-08`).
 *
 * Un `<img src="/api/nutrition/photos/…">` naïf ne fonctionnerait pas : le navigateur
 * n'attache pas le jeton de session à une requête d'image. On récupère donc les octets
 * avec le client API, et on en fait une URL d'objet.
 *
 * L'URL est révoquée au démontage : sans cela, chaque photo affichée fuirait sa mémoire
 * jusqu'au rechargement de la page.
 */

import { useEffect, useState } from 'react';

import { photoPath } from '@/features/nutrition/api';
import { tokenStore } from '@/lib/api';

export function usePhoto(relative: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    // Rien à charger : l'état repart de zéro par la clé de l'effet, pas par un
    // `setState` synchrone qui provoquerait un rendu en cascade.
    if (!relative) return;

    let objectUrl: string | null = null;
    const controller = new AbortController();
    const token = tokenStore.read();

    fetch(photoPath(relative), {
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => {
        if (!blob || controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        // Une vignette absente n'est pas une erreur d'écran : la ligne du repas reste
        // lisible sans elle.
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setUrl(null);
    };
  }, [relative]);

  // Une photo retirée ne doit pas continuer d'afficher l'ancienne.
  return relative ? url : null;
}
