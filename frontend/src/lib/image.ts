/**
 * Réduction d'une image **avant** l'envoi.
 *
 * Une photo d'iPhone 16 Pro fait 4032 × 3024 et cinq à huit mégaoctets. Envoyée telle
 * quelle, elle traverse un reverse-proxy qui plafonne à 1 Mo par défaut, et le refus qui
 * en revient est un `413` nu — c'est le défaut relevé en usage sur « Estimer les macros ».
 * Réduite ici, elle pèse deux ou trois cents kilooctets et le problème n'a plus lieu.
 *
 * **Le serveur réduit déjà, et ce n'est pas un doublon.** `ai/images.py` ramène l'image à
 * 1024 px avant de l'envoyer au modèle — mais il ne peut le faire qu'**après** l'avoir
 * reçue. Toute la difficulté est en amont : le téléversement lui-même. Les deux réductions
 * n'ont donc ni le même but ni le même moment, et celle-ci est plus généreuse (1600 px)
 * pour ne rien retirer à celle-là.
 *
 * Trois choix méritent d'être nommés :
 *
 * * **On ne grandit jamais.** Une image déjà petite est renvoyée telle quelle : réencoder
 *   une capture de 800 px en JPEG lui ferait perdre en netteté sans rien gagner en poids.
 * * **L'orientation EXIF est appliquée**, par `imageOrientation: 'from-image'`. Sans elle,
 *   une photo prise en tenant le téléphone de travers arrive couchée — le canevas dessine
 *   les pixels bruts et perd la métadonnée qui disait comment les lire.
 * * **Un échec de décodage n'est pas une erreur.** Le fichier d'origine repart tel quel et
 *   c'est le serveur qui tranche. C'est ce qui fait qu'un format que le navigateur ne sait
 *   pas ouvrir ne bloque pas la saisie — `IA-07` transposé à l'image.
 */

/** Côté long visé. Au-delà, on paie un téléversement pour des pixels que rien ne lit. */
export const MAX_SIDE = 1600;

/** Qualité JPEG. 0,8 est le seuil au-dessous duquel une assiette commence à baver. */
export const QUALITY = 0.8;

export interface Reduced {
  /** Le fichier à envoyer — le réduit, ou l'original si rien n'a pu être fait. */
  file: File;
  /** Vrai quand l'image a réellement été réencodée. */
  reduced: boolean;
}

/** `1,4 Mo`, `312 ko` — pour dire à l'écran ce qui part réellement. */
export function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} Mo`;
  }
  return `${Math.round(bytes / 1024)} ko`;
}

/**
 * Réduit et réencode une image en JPEG.
 *
 * Rend toujours quelque chose d'envoyable : sur un format que le navigateur ne décode pas
 * — le HEIC d'un iPhone hors de Safari, par exemple —, c'est le fichier d'origine.
 */
export async function reduceImage(
  file: File,
  { maxSide = MAX_SIDE, quality = QUALITY } = {},
): Promise<Reduced> {
  const bitmap = await decode(file);
  if (bitmap === null) return { file, reduced: false };

  try {
    const ratio = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    // Déjà sous la cible **et** déjà en JPEG : la réencoder ne ferait que la dégrader.
    if (ratio === 1 && file.type === 'image/jpeg') return { file, reduced: false };

    const width = Math.round(bitmap.width * ratio);
    const height = Math.round(bitmap.height * ratio);

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (context === null) return { file, reduced: false };
    context.drawImage(bitmap, 0, 0, width, height);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', quality);
    });
    // Un canevas peut refuser d'être lu — une image d'une autre origine le salit. Ce n'est
    // pas le cas ici, un fichier local n'a pas d'origine, mais un `null` reste un `null`.
    if (blob === null || blob.size === 0) return { file, reduced: false };

    // Le réduit n'est pas toujours plus léger : une capture d'écran en PNG plat peut
    // grossir en JPEG. On garde le plus petit des deux, et on le dit.
    if (blob.size >= file.size && ratio === 1) return { file, reduced: false };

    return {
      file: new File([blob], renameToJpeg(file.name), {
        type: 'image/jpeg',
        lastModified: file.lastModified,
      }),
      reduced: true,
    };
  } finally {
    bitmap.close();
  }
}

async function decode(file: File): Promise<ImageBitmap | null> {
  try {
    return await createImageBitmap(file, { imageOrientation: 'from-image' });
  } catch {
    return null;
  }
}

function renameToJpeg(name: string): string {
  const base = name.replace(/\.[^.]+$/, '');
  return `${base || 'photo'}.jpg`;
}
