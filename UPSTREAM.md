Source: https://github.com/home-assistant/core/pull/187939
Branch: snfx-johaver/core@snfx-johaver-special-fishstick

Local packaging changes on top of that PR:
- manifest version + documentation URL for the custom package
- async_setup_entry / unload / migrate return bool
- Bound API response cache growth
- Net grid/storage power for V1-shaped power-flow sensors
- Paste-code OAuth via static redirect
  https://smarthomespecialist.be/solaredge_callback.html
- README install notes
