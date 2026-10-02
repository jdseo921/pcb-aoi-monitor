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
- [REQ-INSP-010] The view picked on the Inspection page (Top, Side or Bottom) is now stored on the inspection record, shown in a new View column on Logs & Export and written to the CSV export; defects already carried it, and a record's view and its defects' side now always agree. / 검사 페이지에서 고른 뷰(Top, Side, Bottom)가 이제 검사 기록에 저장되고, 로그 및 내보내기의 새 View 열에 표시되며, CSV 내보내기에 기록됩니다. 결함에는 이미 뷰가 있었으며, 기록의 뷰와 결함의 Side가 항상 일치합니다.

## Improved / 개선 (draft)

None. / 없음.

## Fixed / 수정 (draft)

None. / 없음.

## Security / 보안 (draft)

None. / 없음.

## Known issues / 알려진 문제 (draft)

None. / 없음.

## Upgrade notes / 업그레이드 안내 (draft)

- [REQ-INSP-010] Migration 0005 adds the view column to inspection records; records from before it show an empty view in Logs & Export and in the CSV, since their view was never recorded. / 마이그레이션 0005가 검사 기록에 뷰 열을 추가합니다. 그 이전 기록은 뷰가 기록된 적이 없으므로 로그 및 내보내기와 CSV에서 빈 뷰로 표시됩니다.
- [REQ-INSP-001] Images over 50 MP or 200 MB that v0.1 inspected are now refused; a station whose camera exceeds either limit raises max_image_megapixels or max_image_megabytes in settings.json in the default workspace folder (~/AOI_Workspace, or $AOI_WORKSPACE). / v0.1에서 검사되던 50 MP 또는 200 MB를 넘는 이미지는 이제 거부됩니다. 카메라가 이를 넘는 스테이션은 기본 작업 폴더(~/AOI_Workspace 또는 $AOI_WORKSPACE)의 settings.json에서 max_image_megapixels 또는 max_image_megabytes를 올립니다.

<!--
Item format: "- [REQ-INSP-005] Start, Stop, Next Board and Save Result work by F5, F6, F8 and F9. / F5, F6, F8, F9 키로
검사 시작, 정지, 다음 보드, 결과 저장을 할 수 있습니다." One line per item, English first, Korean after the slash,
the ID in brackets. A change that can alter a verdict goes in the first section with its before/after result on
the synthetic regression set and a note that customers re-validate before it goes live (Engineering, Change control).
-->
