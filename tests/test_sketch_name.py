"""Test sketch name inspection."""
from sw_mcp.cad.session import get_cad_session

sess = get_cad_session()
doc_mgr = sess.document
sk = sess.sketcher
app = sess.client.app

p = doc_mgr.new_part()
sk.create_sketch("Front Plane")
sk.draw_arc(0.0, 0.0, 40.0, 30.0, 0.0, 30.0)
sk.close_sketch()

doc = doc_mgr.get_active_doc()
feat = doc.FirstFeature
while feat:
    print(f"Feature: Name='{feat.Name}', Type='{feat.GetTypeName2}'")
    feat = feat.GetNextFeature

app.CloseDoc(doc.GetTitle)
