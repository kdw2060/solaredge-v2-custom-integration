# SolarEdge V2 api (custom override)

This custom component is meant as a temporary stopgap until the official integration is working again.

## **WARNING**

Local custom component that **overrides** Home Assistant’s built-in `solaredge`
integration so it uses SolarEdge Monitoring API **V2** with **OAuth Site Access**.

## **Attribution**

Based on upstream [home-assistant/core#187939](https://github.com/home-assistant/core/pull/187939),
extended with a **paste-code OAuth** path for installs without a public Home Assistant URL.
If you do have a public URL for your Home Assistant instance, then you can rewrite this custom component to make use of that.
But otherwhise, feel free to use this component as is.

## Requirements

- Home Assistant **2026.11+**
- Site Access app registered on developer.solaredge.com

## Installation / usage

### 1. Create a SolarEdge Site Access app

1. Go to [developer.solaredge.com](https://developer.solaredge.com/) and create an account. There is a free tier available.
2. Create an application: **Site Access**, service **Monitoring**, OAuth 2.0
3. Scopes: **`SITE_DATA`** and **`DEVICE_DATA`**
4. Redirect URI (exact):

   ```text
   https://smarthomespecialist.be/solaredge_callback.html
   ```

--> This is a simple static page that is placed on a domain I own. Feel free to use.
Your token data is not stored on the domain and stays private to you. If you want you can always host the html file on your own domain and use a different Redirect URI. If you do so you need to update references to this domain in the component's code too.

5. Save **Client ID** and **Client Secret**

### 3. Install the custom component

1. Copy `custom_components/solaredge/` into your HA config as  
   `<config>/custom_components/solaredge/`
2. Restart Home Assistant

### 4. Add / reauth the integration

1. **Settings → Devices & services → Add integration → SolarEdge**  
   (or reload and reauth the existing entry)
2. Enter your numeric **site ID**
3. Create / pick **Application credentials** (Client ID + Secret you saved earlier)
4. HA shows an **authorize link** — open it, sign in as the **site owner**, Approve
5. Browser lands on the static page — **Copy URL**
6. Paste that full URL into HA immediately (codes are short-lived / single-use)

Tokens refresh automatically after that.

## Sensors

Same entities as the core integration (no new ones). Power-flow-named sensors are
filled from Basic meter/storage telemetry (15‑minute samples).


## Uninstall / revert

1. Remove the SolarEdge config entry
2. Delete `<config>/custom_components/solaredge/`
3. Restart HA

## Upstream

Prefer feeding fixes back to [#187939](https://github.com/home-assistant/core/pull/187939)
once validated.
