# Templates

Place here the crops (PNG) of the buttons/icons the bot should recognize.

How to create:

1. With the emulator on the desired screen, run from the project root:
   ```bash
   python capture.py
   ```
   This generates `screen.png` with the current screen.
2. Open `screen.png`, crop **only the button** (tight, without unnecessary
   borders) and save it here with the name expected by the task.

Names currently expected (see/edit in the `tasks/` files):

- `help_balloon.png` → green handshake balloon on the main screen
  (shortcut that helps the whole alliance). **Already created.**
- `home_bottom_menu.png` → World button (bottom menu) = proof of the home
  screen. **Already created.**
- `conquest_button.png` → Conquest button on the bottom bar. **Already created.**
- `conquest_chest.png` → reward chest on the Conquest screen. **Already created.**
- `conquest_claim.png` → CLAIM button in the Idle Income modal. **Already created.**
- `conquest_exit.png` → "Tap anywhere to exit" text. **Already created.**

Pending (Collect VIP daily) — capture the screens at 540x960 and crop:

- `vip_button.png`       → the V-diamond "VIP X" badge in the home top-right
  (crop the constant diamond icon, NOT the changing level number)
- `vip_daily_chest.png`  → the blinking chest (with red dot) on the VIP screen
- `vip_continue.png`     → the "Click to continue" button of the VIP points modal
- `vip_bundle_claim.png` → the green "Claim" of the "VIP X Daily Free Bundle"
  (only shows when VIP is active; never crop the R$ purchase button next to it)
- `vip_rewards_exit.png` → the "Tap anywhere to exit" footer of the bundle modal

Pending (Train troops) — capture the screens at 540x960 and crop:

- `train_troops_available.png` → indicator that training is available
- `train_button.png`           → train button
- `train_confirm.png`          → confirmation (optional)

Terror Hunt (Hunt Terror) — **already created and validated live**:

- `world_search.png`   → the magnifier (search) on the left of the world map
- `terror_icon.png`    → the Terror (lion) tab in the search panel
- `search_button.png`  → the blue "Search" button
- `rally_button.png`   → the orange "Rally" button on a Terror's card
- `rally_5min.png`     → the "5 min(s)" arrival-time option
- `rally_confirm.png`  → the "Hold a rally" button
- `formation_hnt.png`  → the "HNT" formation preset tab (loads Diana + ratio)
- `deploy_button.png`  → the "Deploy" button
- `world_town.png`     → the Town button (bottom-right on the world map)

Beast Hunt (Hunt Beasts) — **created and validated live on emulator 5555**:

- Reuses `world_search.png`, `terror_icon.png`, `search_button.png`,
  `formation_hnt.png`, `diana_hero.png`, and `deploy_button.png`.
- The Beasts tab is selected relative to the Terror label immediately to its
  right, so no animated bear-icon template is required.
- Flow: Beasts → Lv.1-30 (default/max Lv.30) → Search → Attack → HNT → Deploy.
- Unlike Terror Hunt, this is a direct attack: there is no rally-time dialog.

Important rule (free-to-play): NEVER tap real-money purchase buttons (e.g.
"$61.90", monthly cards, offers). Always close with the X or ignore them.

Tips:
- Smaller, very specific crops are more reliable.
- ALWAYS keep the same emulator resolution used to create the templates.
- If a button is not detected, lower `DEFAULT_THRESHOLD` in `config.py`
  (e.g. 0.80) or redo the crop.
