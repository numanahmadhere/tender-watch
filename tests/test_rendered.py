import pytest

pw = pytest.importorskip("playwright")


def test_render_executes_javascript(tmp_path):
    import os
    from tenderwatch.sources.rendered import render
    exe = "/opt/pw-browsers/chromium"
    if not os.path.exists(exe):
        pytest.skip("no chromium available")
    os.environ["TW_CHROMIUM"] = exe
    f = tmp_path / "p.html"
    f.write_text("<html><body><div id=t></div><script>"
                 "document.getElementById('t').innerHTML="
                 "'<table><tr><th>Title</th></tr><tr><td>Rendered by script</td></tr></table>';"
                 "</script></body></html>")
    html = render(f.as_uri())
    assert "Rendered by script" in html
