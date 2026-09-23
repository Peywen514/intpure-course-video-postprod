# brands/default 品牌素材（空白模板）

這個資料夾預設是空的——沒有 `intro.mp4` / `outro.mp4` 之前，`06_bumper_concat.py --brand default`
會丟出清楚的 `FileNotFoundError`，不會靜默失敗。

把你的片頭/片尾影片檔改名成 `intro.mp4` / `outro.mp4` 放進這個資料夾即可生效，
`06_bumper_concat.py` 的呼叫方式不需要改。

要新增其他客戶/品牌：複製整個 `brands/default/` 資料夾、改名成客戶代號，
放進對應的 `intro.mp4` / `outro.mp4`，跑的時候指定 `--brand <客戶代號>` 即可，不需修改程式碼。

> ⚠️ 之前這裡曾放過從真實課程錄影剪下來的測試片段（`input/1-1-未上字幕.mp4`），
> 已移除並改為空白模板——這個資料夾以後只放「可以公開/分享的品牌素材」，
> 不要放真實課程內容或未授權素材。
