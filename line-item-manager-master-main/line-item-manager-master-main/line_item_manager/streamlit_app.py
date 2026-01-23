import tempfile
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

import streamlit as st
import yaml

from .app_runner import CreateOptions, LineItemManagerUsageError, create_line_items, list_bidders, read_resource


def _write_upload(uploaded_file, label: str) -> Optional[str]:
    if uploaded_file is None:
        return None
    tmp_dir = Path(tempfile.gettempdir()) / "line-item-manager"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}_{label}_{uploaded_file.name}"
    path = tmp_dir / filename
    path.write_bytes(uploaded_file.getvalue())
    return str(path)


def _parse_bidder_codes(raw: str) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p]


def _parse_network_code(raw: str) -> Optional[int]:
    if not raw:
        return None
    return int(raw.strip())


def _preview_text(text: str, limit: int = 200) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + "\n..."


@st.cache_data(show_spinner=False)
def _cached_bidders() -> List[dict]:
    return list_bidders()


def _render_resources() -> None:
    st.subheader("Default resources")
    for name in ("config", "template", "settings", "schema"):
        content = read_resource(name)
        st.download_button(
            label=f"Download {name}",
            data=content,
            file_name=f"{name}.yml",
            mime="text/yaml",
        )
        with st.expander(f"Preview {name}"):
            st.code(_preview_text(content), language="yaml")


def _render_bidders() -> None:
    st.subheader("Bidder list")
    refresh = st.button("Refresh bidder list")
    if refresh:
        _cached_bidders.clear()
    try:
        bidders = _cached_bidders()
        st.dataframe(bidders, use_container_width=True)
    except Exception as exc:
        st.warning(f"Unable to load bidders. {exc}")


def _render_run() -> None:
    st.subheader("Run configuration")

    col_left, col_right = st.columns(2)
    with col_left:
        config_upload = st.file_uploader(
            "Configuration YAML (required)",
            type=["yml", "yaml"],
        )
        network_code_raw = st.text_input("Network code (optional)")
        single_order = st.checkbox("Single order")
        bidder_codes_raw = st.text_input(
            "Bidder codes (comma-separated)",
            disabled=single_order,
        )
        test_run = st.checkbox("Test run")
        dry_run = st.checkbox("Dry run")
        skip_auto_archive = st.checkbox("Skip auto archive")
    with col_right:
        key_upload = st.file_uploader(
            "GAM private key JSON (required)",
            type=["json"],
        )
        network_name = st.text_input("Network name (optional)")
        verbose = st.slider("Verbose level", min_value=0, max_value=3, value=0)
        quiet = st.checkbox("Quiet (errors only)")
        show_details = st.checkbox("Show detailed output")

    with st.expander("Optional files"):
        template_upload = st.file_uploader(
            "Line item template (optional)",
            type=["yml", "yaml"],
            key="template-upload",
        )
        settings_upload = st.file_uploader(
            "Settings file (optional)",
            type=["yml", "yaml"],
            key="settings-upload",
        )
        schema_upload = st.file_uploader(
            "Schema file (optional)",
            type=["yml", "yaml"],
            key="schema-upload",
        )

    if config_upload:
        with st.expander("Config preview"):
            content = config_upload.getvalue().decode("utf-8", errors="replace")
            st.code(_preview_text(content), language="yaml")

    run_now = st.button("Run line item manager", type="primary")
    if not run_now:
        return

    errors: List[str] = []
    bidder_codes = _parse_bidder_codes(bidder_codes_raw)
    if not config_upload:
        errors.append("Configuration YAML is required.")
    if not key_upload:
        errors.append("GAM private key JSON is required.")
    if not single_order and not bidder_codes:
        errors.append("Provide at least one bidder code or enable single order.")

    try:
        network_code = _parse_network_code(network_code_raw)
    except ValueError:
        errors.append("Network code must be a number.")
        network_code = None

    if errors:
        for err in errors:
            st.error(err)
        return

    options = CreateOptions(
        configfile=_write_upload(config_upload, "config"),
        network_code=network_code,
        network_name=network_name or None,
        private_key_file=_write_upload(key_upload, "gam-key"),
        template=_write_upload(template_upload, "template"),
        settings=_write_upload(settings_upload, "settings"),
        schema=_write_upload(schema_upload, "schema"),
        single_order=single_order,
        bidder_codes=bidder_codes,
        test_run=test_run,
        dry_run=dry_run,
        quiet=quiet,
        verbose=verbose,
        skip_auto_archive=skip_auto_archive,
    )

    try:
        with st.spinner("Running line item manager..."):
            result = create_line_items(options, include_details=show_details)
    except LineItemManagerUsageError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.exception(exc)
        return

    if result.success:
        st.success("Run completed successfully.")
    else:
        st.warning("Run completed with errors.")

    if result.errors:
        st.subheader("Errors")
        for err in result.errors:
            st.error(err)

    metrics = st.columns(2)
    metrics[0].metric("Line items", result.line_item_count)
    metrics[1].metric("Creative associations", result.lica_count)

    if show_details:
        st.subheader("Output")
        line_items_yaml = yaml.safe_dump(result.line_items, sort_keys=False)
        licas_yaml = yaml.safe_dump(result.licas, sort_keys=False)
        st.download_button(
            "Download line items (YAML)",
            data=line_items_yaml,
            file_name="line_items.yml",
            mime="text/yaml",
        )
        st.download_button(
            "Download creative associations (YAML)",
            data=licas_yaml,
            file_name="line_item_creatives.yml",
            mime="text/yaml",
        )
        with st.expander("Line items preview"):
            st.code(_preview_text(line_items_yaml), language="yaml")
        with st.expander("Creative associations preview"):
            st.code(_preview_text(licas_yaml), language="yaml")


def main() -> None:
    st.set_page_config(page_title="Line Item Manager", layout="wide")
    st.title("Line Item Manager")
    st.caption("Run line-item-manager without the CLI.")

    tabs = st.tabs(["Run", "Resources", "Bidders"])
    with tabs[0]:
        _render_run()
    with tabs[1]:
        _render_resources()
    with tabs[2]:
        _render_bidders()


if __name__ == "__main__":
    main()
