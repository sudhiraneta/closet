"""
Wardrobe Streamlit Page — Closet, Outfit, and Add New tabs.
"""

import streamlit as st


WARDROBE_CSS = """
<style>
/* Wardrobe grid */
.w-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-top: 12px; }
.w-card { background: #fff; border-radius: 16px; overflow: hidden; transition: box-shadow 0.2s; }
.w-card:hover { box-shadow: 0 6px 20px rgba(0,0,0,0.08); }
.w-card img { width: 100%; aspect-ratio: 3/4; object-fit: contain; background: #f7f7f7; }
.w-card-body { padding: 12px 14px 16px 14px; }
.w-card-body .w-name { font-size: 14px; font-weight: 500; color: #222; margin: 0 0 4px 0; }
.w-card-body .w-meta { font-size: 13px; color: #717171; margin: 0; }
.w-stats { font-size: 14px; color: #717171; margin: 4px 0 8px 0; }
.w-stats b { color: #222; font-weight: 600; }
.w-empty { text-align: center; padding: 80px 20px; color: #717171; font-size: 15px; background: #fafafa; border-radius: 16px; margin-top: 16px; }

/* Outfit */
.outfit-weather { background: linear-gradient(135deg, #1a1a2e, #16213e); color: #fff; padding: 16px 22px; border-radius: 16px; font-size: 14px; margin-bottom: 16px; font-weight: 500; letter-spacing: 0.3px; }
.outfit-reasoning { font-size: 14px; color: #555; margin: 0 0 20px 0; line-height: 1.5; }
.outfit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 20px; margin-top: 8px; }
.outfit-piece { text-align: center; background: #fff; border-radius: 16px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.06); transition: box-shadow 0.2s; }
.outfit-piece:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.10); }
.outfit-piece img { width: 100%; aspect-ratio: 3/4; object-fit: contain; background: #f7f7f7; }
.outfit-piece .w-name { font-size: 14px; font-weight: 500; color: #222; margin: 12px 0 4px 0; }
.outfit-piece .w-meta { font-size: 13px; color: #717171; margin: 0 0 12px 0; }
</style>
"""


def render(api_call, api_base: str):
    """Render the wardrobe page with Closet, Outfit, and Add New tabs."""

    st.markdown(WARDROBE_CSS, unsafe_allow_html=True)
    st.title("Wardrobe")

    wardrobe_tab, outfit_tab, add_tab = st.tabs(["Closet", "Outfit", "Add New"])
    IMG_BASE = api_base.replace("/api", "")

    # ---- Closet ----
    with wardrobe_tab:

        # Load data first
        wardrobe_data = api_call("get", "/wardrobe/items")
        items = wardrobe_data.get("items", []) if wardrobe_data else []
        by_cat = wardrobe_data.get("summary", {}).get("by_category", {}) if wardrobe_data else {}

        if items:
            # Filter bar
            cat_map = {"tops": "Tops", "bottoms": "Bottoms", "dresses": "Dresses", "shoes": "Shoes"}
            all_cats = sorted(set(i["category"] for i in items))
            selected = st.radio("filter", ["All"] + [cat_map.get(c, c) for c in all_cats],
                                horizontal=True, label_visibility="collapsed")

            if selected != "All":
                rev = {v: k for k, v in cat_map.items()}
                filtered = [i for i in items if i["category"] == rev.get(selected, selected.lower())]
            else:
                filtered = items

            # Stats
            total = len(wardrobe_data.get("items", [])) if wardrobe_data else 0
            parts = [f"<b>{total}</b> pieces"]
            for c in ["tops", "bottoms", "dresses", "shoes"]:
                if by_cat.get(c):
                    parts.append(f"<b>{by_cat[c]}</b> {c}")
            st.markdown(f'<p class="w-stats">{" · ".join(parts)}</p>', unsafe_allow_html=True)

            # Grid
            html = '<div class="w-grid">'
            for item in filtered:
                img_url = item.get("image_url", "")
                img_src = f"{IMG_BASE}{img_url}" if img_url else ""
                img_tag = f'<img src="{img_src}" />' if img_src else '<div style="height:200px;background:#f7f7f7;"></div>'
                name = item.get("subcategory", "Item")
                color = item.get("color", "")
                season = (item.get("season") or "").replace("_", " ")
                html += (
                    f'<div class="w-card">{img_tag}'
                    f'<div class="w-card-body">'
                    f'<p class="w-name">{name}</p>'
                    f'<p class="w-meta">{color} · {season}</p>'
                    f'</div></div>'
                )
            html += '</div>'
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="w-empty">No items yet — drop photos in ~/Downloads/wardrobe_inbox/ or click + Add</div>',
                unsafe_allow_html=True,
            )

    # ---- Outfit ----
    with outfit_tab:
        c1, c2 = st.columns([5, 1])
        with c1:
            prompt = st.text_input(
                "prompt", label_visibility="collapsed",
                placeholder="I am in NYC for my bday today, suggest party outfits that suit the weather",
            )
        with c2:
            go = st.button("Go", type="primary", use_container_width=True)

        if go and prompt:
            with st.spinner(""):
                from urllib.parse import quote
                result = api_call("post", f"/wardrobe/outfit?prompt={quote(prompt)}")
            if result and not result.get("error"):
                weather = result.get("weather", {})
                city_name = result.get("city", "")
                temp_c = weather.get("temp_c", "?")
                condition = weather.get("condition", "")
                humidity = weather.get("humidity", "?")

                st.markdown(
                    f'<div class="outfit-weather">'
                    f'{city_name or "Local"} &mdash; {temp_c}°C {condition} &middot; {humidity}% humidity'
                    f'</div>'
                    f'<p class="outfit-reasoning">{result.get("reasoning", "")}</p>',
                    unsafe_allow_html=True)

                pieces = [result.get(k) for k in ["top", "dress", "bottom", "shoes"] if result.get(k)]
                if pieces:
                    html = '<div class="outfit-grid">'
                    for item in pieces:
                        img_url = item.get("image_url", "")
                        img_src = f"{IMG_BASE}{img_url}" if img_url else ""
                        img_tag = f'<img src="{img_src}" />' if img_src else ""
                        html += (
                            f'<div class="outfit-piece">{img_tag}'
                            f'<p class="w-name">{item.get("subcategory", "")}</p>'
                            f'<p class="w-meta">{item.get("color", "")}</p></div>'
                        )
                    html += '</div>'
                    st.markdown(html, unsafe_allow_html=True)
            elif result:
                st.error(result.get("error", "Something went wrong"))

    # ---- Add New ----
    with add_tab:
        st.markdown("**Upload a photo** or process photos from your inbox folder.")

        uploaded = st.file_uploader(
            "Drop a photo here", type=["jpg", "jpeg", "png", "webp"],
            label_visibility="visible",
        )
        if uploaded:
            with st.spinner("Analyzing photo and adding to wardrobe..."):
                result = api_call("post", "/wardrobe/items/add",
                                  files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)})
            if result and result.get("items_added", 0) > 0:
                st.success(f"Added {result['items_added']} item(s) to your wardrobe!")
                st.rerun()
            elif result:
                st.warning("No clothing items detected in this photo.")

        st.divider()

        st.markdown(f"**Inbox folder:** `~/Downloads/wardrobe_inbox/`")
        st.caption("Drop photos there and press the button below to process them all at once.")
        if st.button("Process Inbox", use_container_width=True):
            with st.spinner("Processing inbox photos..."):
                result = api_call("post", "/wardrobe/inbox")
            if result and result.get("items_added", 0):
                st.success(f"Added {result['items_added']} item(s), embedded {result.get('items_embedded', 0)}.")
                if result.get("items_skipped_duplicate"):
                    st.info(f"Skipped {result['items_skipped_duplicate']} duplicate items.")
                st.rerun()
            elif result and result.get("status") == "empty":
                st.info("Inbox is empty — drop photos in ~/Downloads/wardrobe_inbox/ first.")
            elif result and result.get("skipped"):
                st.info(f"All {result['skipped']} photos already processed.")
