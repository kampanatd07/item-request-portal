# UoM master — 24 codes (Carabao Group UoM Standard v1)

No unit outside this list. A new unit needs Data Owner approval.

| Code | Name | Thai | Use |
|---|---|---|---|
| EA | Each | ชิ้น / อัน / ตัว / ใบ | countable — default for goods |
| SET | Set | ชุด | sold as an inseparable set |
| PAIR | Pair | คู่ | gloves, shoes |
| PK | Pack | แพ็ค | several pieces in a pack |
| BOX | Box | กล่อง | |
| BAG | Bag | ถุง | |
| BTL | Bottle | ขวด | |
| CAN | Can | กระป๋อง | |
| DRUM | Drum | ถัง | 200 L drum |
| ROLL | Roll | ม้วน | tape, film, cable |
| SHT | Sheet | แผ่น | flat sheet |
| REAM | Ream | รีม | paper |
| M | Metre | เมตร | |
| YD | Yard | หลา | |
| L | Litre | ลิตร | |
| ML | Millilitre | มิลลิลิตร | |
| GAL | Gallon | แกลลอน | |
| KG | Kilogram | กิโลกรัม | |
| G | Gram | กรัม | |
| JOB | Job | งาน / ครั้ง | lump sum — default for services |
| HR | Hour | ชั่วโมง | |
| DAY | Day | วัน / manday | |
| MTH | Month | เดือน | monthly contract |
| YR | Year | ปี | annual contract / license |

## Base vs Purchase UoM

| Field | Meaning | Example |
|---|---|---|
| Base UoM | unit for stock count and costing | PAIR |
| Purchase UoM | unit actually ordered from the vendor | BOX |
| Pack Size | 1 Purchase UoM = N Base UoM | 12 |

Purchase ≠ Base → Pack Size is mandatory.

## Abbreviations found in names → code

| In name | Code |
|---|---|
| ml, มล, cc | ML |
| l, lt, ltr, litre, ลิตร | L |
| kg, กก | KG |
| pcs, pc, ชิ้น, อัน, ตัว, ใบ, ea | EA |
| box, กล่อง | BOX |
| roll, ม้วน | ROLL |
| แผ่น, sheet | SHT |
| ถัง, drum | DRUM |

Likely-wrong defaults to watch: 905-04 Packing material (probably ROLL/BOX, not
EA) and 903 Chemicals (probably L/KG/DRUM, not EA).
