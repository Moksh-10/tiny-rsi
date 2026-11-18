# Art direction and provenance

The visual direction was informed by official gameplay screenshots on:

- https://www.angrybirds.com/games/angry-birds-friends/
- https://www.rovio.com/games/angry-birds-2/

The references informed visual hierarchy, scenery depth, expressive silhouettes, readable materials, and a clear playfield. No reference artwork was downloaded into the game.

## Generated assets

Created with the built-in image generation tool and copied into the repository. The generation mode was text-to-image; transparent alpha was requested for the character atlas. The runtime extracts and trims the eight individual atlas cells using alpha bounds, preserving transparency. There are no placeholder character shapes in the runtime.

### `assets/meadow.png`

Prompt:

> Use case: stylized-concept. Asset type: production background panorama for a polished 2D cartoon slingshot physics game, landscape 16:9. Create a gorgeous hand painted game environment, warm sunny green valley on a whimsical island. Premium mobile game art with crisp silhouettes, painterly texture, atmospheric depth, turquoise sky, fluffy sculpted white clouds, distant blue mountains, vivid rolling lime and emerald hills, a few stylized broadleaf trees at extreme left and right edges, little wildflowers. Side-on view, NOT isometric. Composition: upper 55 percent mostly sky, distant scenery concentrated in lower half; keep middle clear for game objects. Bottom 14 percent is a level straight horizontal grassy ground strip with rich ochre earth below; grass surface exactly 86 percent down image, uninterrupted horizontal floor. No foreground large objects, no buildings, no characters, no slingshots, no blocks, no birds, no pigs, no text, no UI, no logos. Full bleed beautiful detailed illustration with game art polish, no generic geometric flat vector landscape.

### `assets/canyon.png`

Prompt:

> Use case: stylized-concept. Asset type: production environment background for a polished 2D cartoon slingshot game, landscape 16:9. Scene: A warm sunset canyon: amber orange sky, peach clouds, distant violet buttes, stylized sandstone mesas, small prickly cacti at far edges, ochre and terracotta earth, golden grass. Premium hand painted mobile game illustration with crisp silhouettes, painterly textures and atmospheric depth. Side-on view, not isometric. Upper 55 percent mostly open sky, distant scenery concentrated in lower half. Keep the whole middle clear for game physics objects. Bottom 14 percent must be a straight uninterrupted horizontal ground strip with textured earth below; grass surface exactly 86 percent down the image. Rich polished cartoon environment, not flat geometric vector. No buildings, no characters, no birds, no pigs, no blocks, no slingshots, no text, no UI, no logo. Full bleed.

### `assets/night.png`

Prompt:

> Use case: stylized-concept. Asset type: production environment background for a polished 2D cartoon slingshot game, landscape 16:9. Scene: A magical moonlit valley: deep royal blue sky, luminous full moon upper right, tiny stars, layered violet mountains, soft indigo hills, teal woodland at far edges, blue green grass and dark plum earth. Premium hand painted mobile game illustration with crisp silhouettes, painterly textures and atmospheric depth. Side-on view, not isometric. Upper 55 percent mostly open sky, distant scenery concentrated in lower half. Keep the whole middle clear for game physics objects. Bottom 14 percent must be a straight uninterrupted horizontal ground strip with textured earth below; grass surface exactly 86 percent down the image. Rich polished cartoon environment, not flat geometric vector. No buildings, no characters, no birds, no pigs, no blocks, no slingshots, no text, no UI, no logo. Full bleed.

### `assets/characters.png`

Prompt:

> Use case: stylized-concept. Asset type: PRODUCTION 2D GAME CHARACTER SPRITE ATLAS with real transparent alpha, 4 columns by 2 rows, precisely aligned uniform grid, landscape 2:1 aspect ratio, ideally 2048x1024. This is a polished Angry Birds fan game. Create gorgeous professional hand painted cartoon game sprites of these FOUR iconic archetypes in EXACT column order: column 1 Red, the round crimson angry bird with small scarlet head feathers, black tail feathers, cream belly, thick black V eyebrows, two white eyes and a golden triangular beak; column 2 Chuck, the triangular golden yellow bird with black crest and tail, white belly and orange beak; column 3 Bomb, the charcoal black round bird with gray belly, orange brows, small lit fuse, white eyes and golden beak; column 4 a round lime green minion pig with two ears, snout, expressive white eyes, nostrils and small goofy teeth. Row 1: idle alert expressions, bird bodies angled slightly toward right, pig faces camera. Row 2: same four characters at EXACT same size and position in each cell, but birds fierce in-flight expressions and pig dizzy/hurt expression. Consistent premium cel shaded game art, sculpted volume through beautiful colored shading, crisp dark brown outlines, appealing expressive faces, detailed professional painterly finish. Each character is a single isolated complete body, centered within its own cell with at least 12 percent empty transparent margin on every edge; do not overlap cell boundaries. Red and Bomb and pig round, Chuck triangular. Entire background fully transparent, no checkerboard, no ground, no circles behind characters, no cell borders, no labels, no text, no watermarks, no UI, no extra objects or characters. Make this look like real finished mobile game art rather than vector placeholder shapes.

## Other art and sound

Material surfaces, UI, slingshot, particles, typography layout, and star shapes are rendered in C++. Sound effects and three looping musical cues are synthesized at startup; no third-party recordings are used. The app icon is rendered from the same character atlas.

Bangers and Nunito were downloaded from the official Google Fonts repository; their OFL licenses are in `assets/`. The Nunito variable font was instantiated at weight 750 to ensure legibility at small HUD sizes.
