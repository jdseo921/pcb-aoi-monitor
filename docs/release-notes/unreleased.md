# Unreleased / 미출시 (draft, needs native review)

Release notes follow the Engineering standard ("Release notes"): one template, English and Korean together,
a requirement or bug ID on every item, and the first section is never skipped. At release time this file is
renamed to `<version>.md` and a new `unreleased.md` starts empty.

> Korean text in this file is a draft, machine-assisted, and needs review by a native speaker who knows SMT
> terms before it reaches a customer (Customers & Launch, "Both languages").

## Changes that can alter verdicts / 판정에 영향을 줄 수 있는 변경 (draft)

None. / 없음.

## New / 신규 (draft)

- [REQ-INSP-012] An Admin sets how long OK results' maps are kept and the largest image (megapixels and MB) on Settings; before, only in settings.json (#153). / 관리자가 설정 페이지에서 OK 결과 맵 보관 기간과 최대 이미지 크기(메가픽셀, MB)를 설정합니다. 이전에는 settings.json에서만 가능했습니다(#153).
- [REQ-TRN-007] Training and Settings offer a 640 px AI model input size next to 128 to 512, for board models with small defects; 256 px stays the default, and each run keeps its size in its AI model (ADR 0012). 640 px trains about 9 times longer, so it suits a station with a CUDA graphics card. / 학습 및 설정 화면에서 128~512에 더해 640 px AI 모델 입력 크기를 선택할 수 있어 작은 결함이 있는 보드 모델에 사용할 수 있습니다. 기본값은 256 px로 유지되며, 각 학습 실행의 크기는 해당 AI 모델에 저장됩니다(ADR 0012). 640 px는 학습 시간이 약 9배 길어 CUDA 그래픽 카드가 있는 스테이션에 적합합니다.

- [REQ-INSP-013] Review each NG or WARN board on the line: Real defect (F10) or False call (F11, with a reason), on Inspection and on Logs & Export. The verdict never changes; the review, who gave it and when stand beside it and in the audit trail, and Home, the Logs Review column, its summary line and the CSV export (four new columns at the end) count the false calls (ADR 0013). / 라인에서 NG 또는 WARN 보드를 검토합니다: 실제 결함(F10) 또는 오검출(F11, 사유 포함)을 검사 화면과 로그 및 내보내기 화면에서 선택합니다. 판정은 바뀌지 않으며, 검토 결과와 검토자, 시간이 판정 옆과 감사 기록에 저장되고, 홈, 로그의 검토 열과 요약 줄, CSV 내보내기(끝에 4개 열 추가)에서 오검출 수를 셉니다(ADR 0013).

- [REQ-INSP-017] Each shift starts with Shift Check (F7) on Inspection: the board model's master samples, a known-OK board and a known-NG board of each Critical defect type, are judged with the engine in use, and no board is inspected until every verdict is right. A check counts for 12 hours (0 to 24 on Settings) and until the AI model, recipe, Golden board or scale changes; each check is audited, and a failed one raises an NG alarm (ADR 0014). / 각 교대 근무는 검사 화면의 교대 점검(F7)으로 시작합니다. 보드 모델의 마스터 샘플(정상 보드 1개와 치명 결함 유형별 불량 보드 1개)을 현재 엔진으로 판정하며, 모든 판정이 맞을 때까지 보드를 검사하지 않습니다. 점검은 12시간(설정에서 0~24) 동안, 그리고 AI 모델, 레시피, 골든 보드 또는 스케일이 바뀔 때까지 유효합니다. 모든 점검은 감사 기록에 남고, 실패하면 NG 알람이 발생합니다(ADR 0014).

- [REQ-INSP-018] Bare boards: a recipe set to Light copper or Dark copper (Recipe Editor, Thresholds) names each difference outside an ROI Open Circuit, Short Circuit, Mousebite, Spur, Spurious Copper or Pin-hole / Missing Hole; Mousebite, Spur, Spurious Copper and Pin-hole / Missing Hole join the defect types, 37 in all. Names never change a verdict, and the setting is off for every recipe until it is set (ADR 0015). / 베어 보드: 레시피에서 밝은 동박 또는 어두운 동박을 설정하면(레시피 편집기, 임계값) ROI 밖의 각 차이를 단선, 단락, 마우스바이트, 스퍼, 잔류 동박 또는 핀홀/홀 누락으로 이름 붙입니다. 마우스바이트, 스퍼, 잔류 동박, 핀홀/홀 누락이 결함 유형에 추가되어 모두 37개입니다. 이름은 판정을 바꾸지 않으며, 설정하기 전까지 모든 레시피에서 꺼져 있습니다(ADR 0015).

- [REQ-TRN-019] Import Folder… and Add NG Images… read each image's Pascal VOC (.xml) or YOLO (.txt) annotation file, beside it or under a mirrored Annotations/ or labels/ folder: the image is labelled NG with its boxes' type (OK when the file holds no box), and the import stores its boxes as if drawn, audited. A box of a class that is not a defect type is left out and the row says so (ADR 0016). / 폴더 가져오기와 불량 이미지 추가가 각 이미지의 Pascal VOC(.xml) 또는 YOLO(.txt) 주석 파일(이미지 옆 또는 Annotations/, labels/ 폴더)을 읽습니다. 이미지는 상자의 결함 유형으로 불량 라벨이 지정되고(상자가 없으면 정상), 가져오기 시 상자가 직접 그린 것처럼 감사 기록과 함께 저장됩니다. 결함 유형이 아닌 클래스의 상자는 제외되며 해당 행에 표시됩니다(ADR 0016).

- [REQ-TRN-018] Recipe Editor › Thresholds › Learn From Labelled Boards… (Ctrl+L) chooses the Pixel difference, Minimum defect area and fine alignment with the fewest false calls that miss at most 1 % of the boxed defects on the board model's labelled boards, and counts them beside the recipe's own on boards held out of choosing (the locked validation set, or a third drawn with a recorded seed), each count with its 95 % upper bound. Use Learned Values puts them in the fields; Save Recipe stores them as a revision with the counts as its reason. Nothing changes until then. / 레시피 편집기 › 임계값 › 라벨된 보드에서 학습…(Ctrl+L)은 보드 모델의 라벨된 보드에서, 박스로 표시된 결함을 1 % 이하로 놓치는 설정 중 오검출이 가장 적은 픽셀 차이, 최소 결함 면적, 정밀 정렬을 고르고, 선택에 쓰지 않은 보드(잠긴 검증 세트, 또는 기록된 시드로 뽑은 3분의 1)에서 현재 레시피의 값과 나란히 각 수치를 95 % 상한과 함께 셉니다. 학습 값 사용은 값을 입력란에 넣고, 레시피 저장이 그 수치를 사유로 하여 새 리비전으로 저장합니다. 그 전에는 아무것도 바뀌지 않습니다.

- [REQ-RCP-007] Recipe Editor › Thresholds › Fine alignment: each board is matched to the Golden board to a fraction of a pixel before the comparison, for fewer false calls along copper edges, at about 0.1 s more per board. Off by default, and stored only when on, so no existing recipe or verdict changes. / 레시피 편집기 › 임계값 › 정밀 정렬: 비교 전에 각 보드를 골든 보드에 1픽셀 미만 정밀도로 맞춰 구리 가장자리의 오검출을 줄이며, 보드당 약 0.1초가 더 걸립니다. 기본값은 꺼짐이며 켰을 때만 저장되므로 기존 레시피와 판정은 바뀌지 않습니다.

- [REQ-TST-004] AI Model Test › Export Image Overlays (an Admin's, Q58) copies a run's annotated images, one per row named `<row>_<image>_<verdict>.png`, every missed defect and false call first, after a question naming the count, audited on the run as `export.test_overlays`: the Stage 1 annotated images beside the test result CSV. / AI 모델 테스트 › Export Image Overlays(관리자 전용, Q58)는 개수를 묻고 확인한 뒤 실행의 주석 이미지를 행마다 하나씩 `<행>_<이미지>_<판정>.png`로 복사하며, 놓친 결함과 오검출을 먼저 복사하고 실행에 `export.test_overlays`로 감사 기록합니다. 테스트 결과 CSV와 함께 전달하는 1단계 주석 이미지입니다.

- [REQ-LOG-008] Logs & Export has two tabs, Records and Defect types. Defect types counts the listed records' defects by type, most first, as a Pareto chart: per type its defects, the records holding it, how many of those were reviewed and how many as a false call, the running total and the share, with a bar for each type. It follows the filter and every review saved, and is read in the background. Every role sees it. / 로그 및 내보내기에 Records와 Defect types 두 탭이 생겼습니다. Defect types는 목록에 있는 기록의 결함을 유형별로 많은 순서대로 세어 파레토 차트로 보여 줍니다. 유형마다 결함 수, 그 유형이 있는 기록 수, 그중 검토된 수와 오검출로 검토된 수, 누적 비율과 점유율을 막대와 함께 보여 줍니다. 필터와 저장된 검토를 따라가며 백그라운드에서 읽습니다. 모든 역할이 볼 수 있습니다.

- [REQ-LOG-009] Logs & Export has a Review filter after Result: Not reviewed (the NG and WARN boards no one has reviewed yet), Real defect or False call. An export's audit entry records it with the rest of the filter. Where the window is narrower than the filters, as at 1600 px, they wrap onto a second row instead of scrolling the page sideways. / 로그 및 내보내기의 결과 필터 뒤에 검토 필터가 생겼습니다: 미검토(아직 아무도 검토하지 않은 NG 및 WARN 보드), 실제 불량, 오검출. 내보내기의 감사 기록에 다른 필터와 함께 남습니다. 창이 필터보다 좁으면(예: 1600 px) 페이지를 옆으로 스크롤하는 대신 필터가 두 번째 줄로 넘어갑니다.

## Improved / 개선 (draft)

- [REQ-SET-004] Text on the green, red and blue fills (verdict banner, Start, Stop, primary and danger buttons) is black, reading at 5.0:1 or more; it was white at 3.3 to 4.2:1 (#150). / 녹색, 빨간색, 파란색 배경 위 글자(판정 배너, 시작, 정지, 주요 및 위험 버튼)가 검은색이 되어 5.0:1 이상으로 읽힙니다. 이전에는 흰색으로 3.3~4.2:1이었습니다(#150).
- [REQ-INSP-002] Defect box labels on Inspection, Compare and AI Model Test, and in the saved overlay, carry the severity word and shape: "1 Polarity Error ◆ Critical", ■ Major, ● Minor (#152). / 검사, 비교, AI 모델 테스트 화면과 저장된 오버레이의 결함 상자 라벨에 심각도 단어와 모양이 표시됩니다: "1 Polarity Error ◆ Critical", ■ Major, ● Minor(#152).
- [REQ-INSP-016] Home's second step card reads "Train AI model" (was "Self-train") (#154). / 홈의 두 번째 단계 카드 이름이 "Train AI model"이 되었습니다(이전 "Self-train")(#154).

- [REQ-SET-004] Ctrl+1 to Ctrl+9 open the sidebar's pages from any page, F1 lists the keys of the page shown and the pages the role opens, and the sidebar names each page's key in its tooltip. Home greys a card whose page the role cannot open and reads "For Engineer / Admin", so an Operator's Home has no button that leads nowhere. / Ctrl+1~Ctrl+9로 어느 페이지에서나 사이드바의 페이지를 열 수 있고, F1은 현재 페이지의 단축키와 역할이 열 수 있는 페이지를 보여 주며, 사이드바 툴팁에 각 페이지의 단축키가 표시됩니다. 홈에서 역할이 열 수 없는 페이지의 카드는 회색으로 표시되고 열 수 있는 역할을 알려 주므로, 작업자의 홈에는 아무 곳으로도 가지 않는 버튼이 없습니다.

- [REQ-TST-004] AI Model Test's Export CSV asks first, naming how many images, as Logs & Export and Export Image Overlays do, and writes the file without holding up the window. / AI 모델 테스트의 Export CSV는 로그 및 내보내기와 Export Image Overlays처럼 이미지 개수를 먼저 묻고, 창을 멈추지 않고 파일을 씁니다.

## Fixed / 수정 (draft)

- [REQ-SET-004] Every page scrolls where the screen is smaller than the page, so a 1366 × 768 station shows every control; before, the window could not shrink below about 1886 × 821 px and the right-hand controls sat off-screen (#104). / 화면이 페이지보다 작으면 모든 페이지가 스크롤되어 1366 × 768 스테이션에서도 모든 컨트롤이 보입니다. 이전에는 창이 약 1886 × 821 px 아래로 줄어들지 않아 오른쪽 컨트롤이 화면 밖에 있었습니다(#104).
- [REQ-SET-004] A long folder, board model or file name, even one with no _ or -, no longer widens the window past the screen: AI Model Test's folder line and note, Compare's labels and Inspection's summary line wrap it, and a line that cuts it shows it whole in its tooltip (#251). / 긴 폴더, 보드 모델 또는 파일 이름(_ 나 - 가 없는 이름 포함)이 더 이상 창을 화면보다 넓히지 않습니다. AI 모델 테스트의 폴더 줄과 안내, 비교 화면의 라벨, 검사 화면의 요약 줄이 줄을 바꾸며, 이름이 잘리면 툴팁에 전체 이름이 표시됩니다(#251).
- [REQ-SET-004] On Logs & Export, the Board model and Operator filters keep their width; a moment after the page opened, the Board model list could shrink and leave a gap beside it. / 로그 및 내보내기에서 보드 모델과 작업자 필터가 너비를 유지합니다. 이전에는 페이지가 열린 직후 보드 모델 목록이 줄어들어 옆에 빈칸이 생길 수 있었습니다.
- [REQ-SET-007] On the demo workspace, Verify Manifest finds the demo's dataset version unchanged; before, it found the manifest missing and marked the version changed for the session. / 데모 작업 공간에서 Verify Manifest가 데모 데이터셋 버전을 변경 없음으로 확인합니다. 이전에는 매니페스트가 없다고 나오고 해당 세션 동안 버전이 변경됨으로 표시되었습니다.
- [REQ-TST-008] The validation report says its targets are the product's proposed defaults, as a customer's own are not yet stored with a run, and that its time per image is the engine's, without reading the file, saving or display; before, it headed them "Targets agreed before testing". / 검증 보고서가 목표를 제품의 제안 기본값이라고 밝히고(고객이 합의한 목표는 아직 실행과 함께 저장되지 않음), 이미지당 시간이 파일 읽기·저장·표시를 뺀 엔진 시간임을 밝힙니다. 이전 제목은 "사전 합의 목표"였습니다.
- [REQ-RCP-005] The Recipe Editor's AOI checks tab says a check covered by the whole board is found as a difference from the Golden board and named Anomaly; before, it said only that the AI model and the comparison cover it. / 레시피 편집기의 AOI 검사 탭이 보드 전체로 다루는 검사는 Golden board와의 차이로 찾아 Anomaly로 이름 붙인다고 밝힙니다.

## Security / 보안 (draft)

- [REQ-USR-001] Only an Admin exports customer results: Export CSV and Export Image Overlays on Logs & Export, Export CSV, Export Report and Validation Report… on AI Model Test, and Export Manifest… on Training are hidden for an Engineer and refused with AOI-USR-001 (#151). Save Image… (F9) on Inspection is the Admin's too. / 고객 결과는 관리자만 내보낼 수 있습니다. 로그 및 내보내기, AI 모델 테스트, 학습 페이지의 내보내기 버튼은 엔지니어에게 숨겨지고 AOI-USR-001로 거부됩니다(#151). 검사 화면의 이미지 저장(F9)도 관리자만 사용할 수 있습니다.

## Known issues / 알려진 문제 (draft)

None. / 없음.

## Upgrade notes / 업그레이드 안내 (draft)

- [REQ-INSP-013] Migration 0023 adds the review columns to each inspection record at the first start; records before it read as not reviewed. A reader of the CSV export finds four columns after ai_check: review, review_reason, review_by, review_time. / 마이그레이션 0023이 첫 시작 시 검사 기록에 검토 열을 추가합니다. 이전 기록은 검토되지 않은 것으로 표시됩니다. CSV 내보내기에는 ai_check 뒤에 review, review_reason, review_by, review_time 4개 열이 추가됩니다.

- [REQ-INSP-017] After the upgrade, Inspection asks for Shift Check (F7) before the first board of each board model; a board model needs a labelled OK sample and a labelled NG sample for it. Migration 0024 adds the shift_checks table. An Admin can set the hours to 0 on Settings while samples are gathered (ADR 0014). / 업그레이드 후 검사 화면은 각 보드 모델의 첫 보드 전에 교대 점검(F7)을 요청합니다. 보드 모델에는 라벨이 지정된 정상 샘플과 불량 샘플이 필요합니다. 마이그레이션 0024가 shift_checks 테이블을 추가합니다. 샘플을 모으는 동안 관리자는 설정에서 시간을 0으로 설정할 수 있습니다(ADR 0014).

- [REQ-USR-001] An Engineer who exported results before now asks an Admin to do it (#151). / 이전에 결과를 내보내던 엔지니어는 이제 관리자에게 요청해야 합니다(#151).

<!--
Item format: "- [REQ-INSP-005] Start, Stop, Next Board and Save Result work by F5, F6, F8 and F9. / F5, F6, F8, F9 키로
검사 시작, 정지, 다음 보드, 결과 저장을 할 수 있습니다." One line per item, English first, Korean after the slash,
the ID in brackets. A change that can alter a verdict goes in the first section with its before/after result on
the synthetic regression set and a note that customers re-validate before it goes live (Engineering, Change control).
-->
