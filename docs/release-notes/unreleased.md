# Unreleased / 미출시 (draft, needs native review)

Release notes follow the Engineering standard ("Release notes"): one template, English and Korean together,
a requirement or bug ID on every item, and the first section is never skipped. At release time this file is
renamed to `<version>.md` and a new `unreleased.md` starts empty.

> Korean text in this file is a draft, machine-assisted, and needs review by a native speaker who knows SMT
> terms before it reaches a customer (Customers & Launch, "Both languages").

## Changes that can alter verdicts / 판정에 영향을 줄 수 있는 변경 (draft)

None. / 없음.

## New / 신규 (draft)

- (none yet)

## Improved / 개선 (draft)

- [REQ-LOG-004] Errors from the engine and data layer carry a code AOI-<AREA>-<NNN> from one catalogue ([docs/error-codes.md](../error-codes.md)) and say what happened and what to do (#4, part). / 엔진과 데이터 계층의 오류에 하나의 목록([docs/error-codes.md](../error-codes.md))에서 가져온 AOI-<영역>-<번호> 코드가 붙고, 무슨 일이 있었는지와 어떻게 해야 하는지를 알려줍니다 (#4, 일부).
- [REQ-INSP-007] The golden-board comparison step is rewritten for speed: about 20 times faster at 5 MP and 12 times at 0.3 MP on a 4-core test VM (not the reference PC), with identical difference maps, masks and regions and the same verdicts on the synthetic regression set (#12). / 골든 보드 비교 단계를 더 빠르게 다시 작성했습니다: 4코어 테스트 VM(기준 PC 아님)에서 5 MP 기준 약 20배, 0.3 MP 기준 약 12배 빠르며, 합성 회귀 세트에서 차이 지도, 마스크, 영역과 판정이 동일합니다 (#12).

## Fixed / 수정 (draft)

- [REQ-SET-016] The database is created and changed only through numbered migrations recorded in the workspace, and it runs in write-ahead-log mode with a full sync on every commit, so a finished write survives a power cut (#2, part). / 데이터베이스는 작업 폴더에 기록되는 번호 매긴 마이그레이션으로만 생성·변경되며, 매 커밋마다 완전 동기화하는 WAL 모드로 동작하여 완료된 기록이 전원 차단에도 남습니다 (#2, 일부).
- [REQ-SET-017] Inspections, AI models, recipes, samples and users carry a UUID beside their local number, and every time is stored in UTC with an offset and shown in local time (#2, part). / 검사, AI 모델, 레시피, 샘플, 사용자 기록에 로컬 번호와 함께 UUID가 붙고, 모든 시각은 오프셋이 있는 UTC로 저장되어 현지 시각으로 표시됩니다 (#2, 일부).
- [REQ-SET-001] Image, overlay and AI model paths are stored relative to the workspace, so a workspace folder can be moved or restored from a backup and every image, model and result still opens (#2). / 이미지, 오버레이, AI 모델 경로를 작업 폴더 기준 상대 경로로 저장하므로 작업 폴더를 옮기거나 백업에서 복원해도 모든 이미지, 모델, 결과가 열립니다 (#2).
- [REQ-INSP-008] Every file the app writes is written whole or not at all (temporary file, flush, atomic rename), and an inspection's record and its defects are saved in one transaction, so a crash or power cut leaves no half-written result; 20 process kills in the test suite lost no finished result (#2). / 앱이 쓰는 모든 파일은 전체가 기록되거나 전혀 기록되지 않으며(임시 파일, 플러시, 원자적 이름 변경), 검사 기록과 결함은 한 트랜잭션으로 저장되므로 충돌이나 전원 차단 시 반쯤 기록된 결과가 남지 않습니다. 테스트에서 20회 프로세스 강제 종료 후 완료된 결과가 하나도 사라지지 않았습니다 (#2).

## Security / 보안 (draft)

- [REQ-TRN-014] AI model files load as weights only on PyTorch 2.6 or later; a file that needs code to load is refused with an error naming the file (#1). / AI 모델 파일은 PyTorch 2.6 이상에서 가중치 전용으로만 불러오며, 코드 실행이 필요한 파일은 파일명을 알리는 오류와 함께 거부됩니다 (#1).

## Known issues / 알려진 문제 (draft)

- (none yet)

## Upgrade notes / 업그레이드 안내 (draft)

- [REQ-TRN-014] AI model files written by v0.1 no longer load; retrain after upgrading. v0.1 workspaces hold test data only and are not upgraded (ADR 0001). / v0.1이 만든 AI 모델 파일은 더 이상 불러올 수 없으므로 업그레이드 후 다시 학습합니다. v0.1 작업 폴더는 테스트 데이터만 담고 있으며 업그레이드되지 않습니다 (ADR 0001).
- [REQ-SET-016] A workspace created by v0.1 is refused at start-up with a message; choose a new workspace folder in Settings (ADR 0004). A workspace on a network drive is refused too. / v0.1이 만든 작업 폴더는 시작 시 안내 메시지와 함께 거부되므로 설정에서 새 작업 폴더를 선택합니다 (ADR 0004). 네트워크 드라이브의 작업 폴더도 거부됩니다.

<!--
Item format: "- [REQ-INSP-005] Start, Stop, Next Board and Save Result work by F5, F6, F8 and F9. / F5, F6, F8, F9 키로
검사 시작, 정지, 다음 보드, 결과 저장을 할 수 있습니다." One line per item, English first, Korean after the slash,
the ID in brackets. A change that can alter a verdict goes in the first section with its before/after result on
the synthetic regression set and a note that customers re-validate before it goes live (Engineering, Change control).
-->
