# Unreleased / 미출시 (draft, needs native review)

Release notes follow the Engineering standard ("Release notes"): one template, English and Korean together,
a requirement or bug ID on every item, and the first section is never skipped. At release time this file is
renamed to `<version>.md` and a new `unreleased.md` starts empty.

> Korean text in this file is a draft, machine-assisted, and needs review by a native speaker who knows SMT
> terms before it reaches a customer (Customers & Launch, "Both languages").

## Changes that can alter verdicts / 판정에 영향을 줄 수 있는 변경 (draft)

None. / 없음.

## New / 신규 (draft)

- [REQ-INSP-001] An image file is checked before it is decoded: its format is read from its content, not its name; a file over 200 MB or an image over 50 MP by its header is refused with AOI-INSP-005, an image with a side over 1,048,576 px with AOI-INSP-007, a file that holds no PNG, JPG, BMP or TIFF image with AOI-INSP-004 and a file that is damaged, cut short or gives no size with AOI-INSP-006; the run stops at that board with the message and Next Board carries on. The two limits are settings (max_image_megapixels and max_image_megabytes in settings.json, in the default workspace folder), checked when the app starts: a wrong value is refused with AOI-SET-008. Sample import is not checked yet. / 이미지 파일을 디코딩하기 전에 검사합니다. 형식은 파일 이름이 아닌 내용으로 판별하며, 200 MB를 넘는 파일이나 헤더 기준 50 MP를 넘는 이미지는 AOI-INSP-005로, 한 변이 1,048,576 px를 넘는 이미지는 AOI-INSP-007로, PNG·JPG·BMP·TIFF 이미지가 아닌 파일은 AOI-INSP-004로, 손상되거나 잘렸거나 크기를 읽을 수 없는 파일은 AOI-INSP-006으로 거부합니다. 검사는 해당 보드에서 메시지와 함께 멈추고 다음 보드로 이어집니다. 두 한도는 설정값이며(기본 작업 폴더의 settings.json에 있는 max_image_megapixels, max_image_megabytes) 앱 시작 시 확인합니다. 잘못된 값은 AOI-SET-008로 거부됩니다. 샘플 가져오기는 아직 검사하지 않습니다.
- [REQ-INSP-005] Start (F5), Stop (F6), Next Board (F8) and Save Image… (F9) work by key and by button, and each button shows its key; Load Images… (Ctrl+O), Load Folder… (Ctrl+Shift+O) and the view (Alt+V cycles Top, Side, Bottom) have keys too. The keys work wherever the focus is on the Inspection page, and only there. Each action answers within 100 ms, before the result: the banner turns grey with "Inspecting…", the buttons that cannot act go grey with their keys, and the status bar names the board and its place in the queue; Stop says it waits for the board in hand. The first board's model load no longer runs on the window's thread. / 검사 시작(F5), 정지(F6), 다음 보드(F8), 이미지 저장…(F9)을 키와 버튼 모두로 할 수 있으며 각 버튼에 키가 표시됩니다. 이미지 불러오기(Ctrl+O), 폴더 불러오기(Ctrl+Shift+O), 뷰 전환(Alt+V: Top, Side, Bottom 순환)에도 키가 있습니다. 키는 검사 페이지 어디에 포커스가 있어도, 그리고 그 페이지에서만 동작합니다. 모든 동작은 결과가 나오기 전에 100 ms 안에 반응합니다. 배너가 회색으로 바뀌며 "검사 중…"을 표시하고, 동작할 수 없는 버튼은 키와 함께 회색이 되며, 상태 표시줄에 보드 이름과 대기열 순서가 표시됩니다. 정지는 진행 중인 보드가 끝날 때까지 기다린다고 알립니다. 첫 보드의 모델 로드가 더 이상 창의 스레드에서 실행되지 않습니다.
- [REQ-INSP-008] Every result is recorded as it arrives, before the next board starts: the verdict, every check with its value, threshold, rule and result, the defects and the comparison metrics, as one record. The Auto-save switch is gone, and Save Result (F9) is now Save Image…, which writes the board picture with its defect boxes to a file you choose and makes no second record. A result that cannot be saved (the disk full, the workspace not writable) stops the run with AOI-INSP-008 and leaves no half record. / 모든 결과가 다음 보드가 시작되기 전에 도착하는 즉시 기록됩니다. 판정, 각 검사 항목의 값·임계값·규칙·결과, 결함, 비교 지표가 하나의 기록으로 저장됩니다. 자동 저장 스위치는 없어졌고, 결과 저장(F9)은 이미지 저장…으로 바뀌어 결함 상자가 표시된 보드 그림을 선택한 파일에 기록하며 기록을 추가로 만들지 않습니다. 결과를 저장할 수 없으면(디스크 가득 참, 작업 폴더 쓰기 불가) 검사가 AOI-INSP-008과 함께 멈추고 불완전한 기록은 남지 않습니다.
- [REQ-INSP-012] Each record names the AI model version and the recipe revision that decided it, by version and by UUID, and keeps its checks in a new checks table with region, metric, value, threshold, rule and result. A board model's default recipe is stored as revision 1 when the board model is created or its first samples are imported, and once at the first start for board models that exist without one, so every record names a stored revision; the Home page still says the recipe uses defaults until an Engineer saves one, and the Recipe Editor's revision list shows revision 1 as the system's. / 각 기록은 판정에 사용된 AI 모델 버전과 레시피 리비전을 버전과 UUID로 명시하고, 새 checks 테이블에 검사 항목별 영역·지표·값·임계값·규칙·결과를 보관합니다. 보드 모델을 만들거나 첫 샘플을 가져올 때, 그리고 리비전이 없는 기존 보드 모델은 첫 실행 시 한 번, 기본 레시피가 리비전 1로 저장되므로 모든 기록이 저장된 리비전을 가리킵니다. 엔지니어가 레시피를 저장하기 전까지 홈 화면은 여전히 기본값 사용으로 표시하며, 레시피 편집기의 리비전 목록에는 리비전 1이 시스템 항목으로 보입니다.
- [REQ-INSP-012] The CSV export of Logs & Export writes a second file beside the first, `<name>_checks.csv`, with one row per check: region, metric, source, value, threshold, rule and result, with the record's time, board model, view, AI model version and recipe revision and their UUIDs; the records file keeps its columns and gains the three UUIDs at the end; records from before migration 0006 have no rows in the second file, whose header is written all the same. / 로그 및 내보내기의 CSV 내보내기가 첫 파일 옆에 두 번째 파일 `<이름>_checks.csv`를 씁니다. 검사 항목마다 한 행으로 영역·지표·출처·값·임계값·규칙·결과를 기록하고, 기록의 시각, 보드 모델, 뷰, AI 모델 버전과 레시피 리비전 및 그 UUID를 함께 적습니다. 기록 파일은 기존 열을 유지하고 끝에 UUID 세 열이 추가됩니다. 마이그레이션 0006 이전 기록은 두 번째 파일에 행이 없지만 머리글은 기록됩니다.
- [REQ-INSP-012] Each record keeps the two maps it was judged on as PNG files beside its overlay picture: the difference against the golden board and the AI score map. The maps of OK results are deleted at the next start once they are older than map_retention_days_ok days (7; a setting in settings.json, in the default workspace folder); NG and WARN maps are kept. / 각 기록은 판정에 사용된 두 맵, 골든 보드와의 차이 맵과 AI 점수 맵을 오버레이 그림 옆에 PNG 파일로 보관합니다. OK 결과의 맵은 map_retention_days_ok일(기본 7일, 기본 작업 폴더 settings.json의 설정값)이 지나면 다음 실행 시 삭제되며 NG와 WARN의 맵은 보관됩니다.
- [REQ-INSP-010] The view picked on the Inspection page (Top, Side or Bottom) is now stored on the inspection record, shown in a new View column on Logs & Export and written to the CSV export; defects already carried it, and a record's view and its defects' side now always agree. / 검사 페이지에서 고른 뷰(Top, Side, Bottom)가 이제 검사 기록에 저장되고, 로그 및 내보내기의 새 View 열에 표시되며, CSV 내보내기에 기록됩니다. 결함에는 이미 뷰가 있었으며, 기록의 뷰와 결함의 Side가 항상 일치합니다.

## Improved / 개선 (draft)

- [REQ-INSP-002] The verdict banner is painted first, within 100 ms of the result, before the board image and the defect list are drawn from it. / 판정 배너가 결과 후 100 ms 안에, 보드 이미지와 결함 목록보다 먼저 그려집니다.
- [REQ-SET-021] A result is saved (overlay, maps, record) on the background thread that inspected the board, so the keys and the Stop button answer during the save; before, the save ran on the window's thread between boards. / 결과 저장(오버레이, 맵, 기록)이 보드를 검사한 백그라운드 스레드에서 이루어져 저장 중에도 키와 정지 버튼이 반응합니다. 이전에는 보드 사이에 창의 스레드에서 저장했습니다.

## Fixed / 수정 (draft)

- [#120] Start and Next Board are disabled while a board is being inspected, so one inspection runs at a time per page; before, Start pressed during Next Board's inspection started a second inspection on the same engine. / 보드를 검사하는 동안 시작과 다음 보드가 비활성화되어 페이지당 한 번에 하나의 검사만 실행됩니다. 이전에는 다음 보드 검사 중에 시작을 누르면 같은 엔진에서 두 번째 검사가 시작되었습니다.

## Security / 보안 (draft)

None. / 없음.

## Known issues / 알려진 문제 (draft)

None. / 없음.

## Upgrade notes / 업그레이드 안내 (draft)

- [REQ-INSP-010] Migration 0005 adds the view column to inspection records; records from before it show an empty view in Logs & Export and in the CSV, since their view was never recorded. / 마이그레이션 0005가 검사 기록에 뷰 열을 추가합니다. 그 이전 기록은 뷰가 기록된 적이 없으므로 로그 및 내보내기와 CSV에서 빈 뷰로 표시됩니다.
- [REQ-INSP-012] Migration 0006 adds model_uuid, recipe_uuid and result_json to inspection records and the checks table; records from before it show no checks and no UUIDs, since their thresholds were never stored. A board model that had no recipe revision gets the default recipe stored as revision 1 at the first start, with an audit entry; a board model that already had revisions is unchanged, and no verdict changes. / 마이그레이션 0006이 검사 기록에 model_uuid, recipe_uuid, result_json을 추가하고 checks 테이블을 만듭니다. 그 이전 기록은 임계값이 저장된 적이 없으므로 검사 항목과 UUID가 비어 있습니다. 레시피 리비전이 없던 보드 모델은 첫 실행 시 기본 레시피가 리비전 1로 저장되며 감사 항목이 남습니다. 이미 리비전이 있는 보드 모델은 바뀌지 않고, 판정도 바뀌지 않습니다.
- [REQ-INSP-012] Migration 0007 adds diff_map_path and ai_map_path to inspection records; records from before it name no maps. The new setting map_retention_days_ok (7 days) is read from settings.json; a value below 0 or of the wrong type is refused with AOI-SET-008. / 마이그레이션 0007이 검사 기록에 diff_map_path와 ai_map_path를 추가합니다. 그 이전 기록에는 맵이 없습니다. 새 설정 map_retention_days_ok(7일)는 settings.json에서 읽으며, 0보다 작거나 형식이 틀린 값은 AOI-SET-008로 거부됩니다.
- [REQ-INSP-001] Images over 50 MP or 200 MB that v0.1 inspected are now refused; a station whose camera exceeds either limit raises max_image_megapixels or max_image_megabytes in settings.json in the default workspace folder (~/AOI_Workspace, or $AOI_WORKSPACE). / v0.1에서 검사되던 50 MP 또는 200 MB를 넘는 이미지는 이제 거부됩니다. 카메라가 이를 넘는 스테이션은 기본 작업 폴더(~/AOI_Workspace 또는 $AOI_WORKSPACE)의 settings.json에서 max_image_megapixels 또는 max_image_megabytes를 올립니다.

<!--
Item format: "- [REQ-INSP-005] Start, Stop, Next Board and Save Result work by F5, F6, F8 and F9. / F5, F6, F8, F9 키로
검사 시작, 정지, 다음 보드, 결과 저장을 할 수 있습니다." One line per item, English first, Korean after the slash,
the ID in brackets. A change that can alter a verdict goes in the first section with its before/after result on
the synthetic regression set and a note that customers re-validate before it goes live (Engineering, Change control).
-->
