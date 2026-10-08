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

- [REQ-INSP-007] The golden-board comparison step is rewritten for speed: about 20 times faster at 5 MP and 12 times at 0.3 MP on a 4-core test VM (not the reference PC), with identical difference maps, masks and regions and the same verdicts on the synthetic regression set (#12). / 골든 보드 비교 단계를 더 빠르게 다시 작성했습니다: 4코어 테스트 VM(기준 PC 아님)에서 5 MP 기준 약 20배, 0.3 MP 기준 약 12배 빠르며, 합성 회귀 세트에서 차이 지도, 마스크, 영역과 판정이 동일합니다 (#12).

## Fixed / 수정 (draft)

- (none yet)

## Security / 보안 (draft)

- [REQ-TRN-014] AI model files load as weights only on PyTorch 2.6 or later; a file that needs code to load is refused with an error naming the file (#1). / AI 모델 파일은 PyTorch 2.6 이상에서 가중치 전용으로만 불러오며, 코드 실행이 필요한 파일은 파일명을 알리는 오류와 함께 거부됩니다 (#1).

## Known issues / 알려진 문제 (draft)

- (none yet)

## Upgrade notes / 업그레이드 안내 (draft)

- [REQ-TRN-014] AI model files written by v0.1 no longer load; retrain after upgrading. v0.1 workspaces hold test data only and are not upgraded (ADR 0001). / v0.1이 만든 AI 모델 파일은 더 이상 불러올 수 없으므로 업그레이드 후 다시 학습합니다. v0.1 작업 폴더는 테스트 데이터만 담고 있으며 업그레이드되지 않습니다 (ADR 0001).

<!--
Item format: "- [REQ-INSP-005] Start, Stop, Next Board and Save Result work by F5, F6, F8 and F9. / F5, F6, F8, F9 키로
검사 시작, 정지, 다음 보드, 결과 저장을 할 수 있습니다." One line per item, English first, Korean after the slash,
the ID in brackets. A change that can alter a verdict goes in the first section with its before/after result on
the synthetic regression set and a note that customers re-validate before it goes live (Engineering, Change control).
-->
