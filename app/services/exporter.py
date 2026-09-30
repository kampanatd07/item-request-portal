"""Build AX/D365 import files matching each factory's template.

Each factory has a distinct format (see docs/rules/export-templates.md). We
reproduce the exact sheet names + column headers from the temp files and fill:
  - variable fields  -> from the request (code, name, search name, uom, price,
                        procurement category) and the group export mapping
  - fixed fields     -> structural constants embedded below

Group-dependent codes (ItemGroupId/ModelGroupId/GroupTypeCode) come from
GroupExportMap config; where unset we fall back to the template default and the
row is still produced (Peter completes the mapping over time).
"""

import io

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, ExportBatch, GroupExportMap, ItemRequest

FILENAME_HINT = {
    "CBD": "CBD_ReleasedProduct",
    "APM": "APM_Items",
    "APG": "APG_Items",
    "ACM": "ACM_Item_Update",
}


class ExportError(Exception):
    """Domain error with a user-facing Thai message."""


def _resolve(db: Session, req: ItemRequest) -> dict:
    """Per-item values shared by all factory formats."""
    top_group = req.group
    mp = db.scalar(
        select(GroupExportMap).where(GroupExportMap.code_group_id == top_group.id)
    )
    # Product type is a property of the sub-category in the group taxonomy
    # (fall back to the parent group, then to the legacy system-name guess).
    declared = (req.subgroup.product_type if req.subgroup else None) or top_group.product_type
    if declared:
        is_service = declared.lower() == "service"
    else:
        is_service = req.code_system.code.endswith("SERVICE")
    return {
        "code": req.generated_code or "",
        "name": req.item_name,
        "search": req.search_name or req.item_name[:60],
        "uom": req.uom or "Pcs",
        "price": req.purchase_price or "",
        "category": req.procurement_category or "",
        "product_type": "Service" if is_service else "Item",
        "item_group_id": (mp.item_group_id if mp else None) or "",
        "model_group_id": (mp.model_group_id if mp else None) or "",
        "group_type_code": (mp.group_type_code if mp else None) or "SP",
    }


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list]):
    ws = wb.create_sheet(title) if wb.sheetnames != ["Sheet"] else wb.active
    if ws.title == "Sheet":
        ws.title = title
    ws.append(headers)
    for r in rows:
        ws.append(r)


# --- CBD: single released-product sheet + WMS -------------------------------
CBD_HEADERS = [
    "ItemId", "DisplayProductNumber", "EcoResProductTranslation_LanguageId",
    "ProductType", "ProductSubType", "EcoResProductTranslation_Name", "NameAlias",
    "SearchName", "ItemGroupId", "EcoResProductDimensionGroup_Name",
    "EcoResStorageDimensionGroup_Name", "EcoResTrackingDimensionGroup_Name",
    "ModelGroupId", "InventTableModulePurch_UnitId", "InventTableModuleInvent_UnitId",
    "InventTableModuleSales_UnitId", "BOMUnitId", "InventTableModulePurch_TaxItemGroupId",
    "InventTableModuleSales_TaxItemGroupId", "PurchModel", "CostModel",
]


def _build_cbd(db, requests):
    wb = Workbook()
    main, wms = [], []
    for req in requests:
        v = _resolve(db, req)
        main.append([
            v["code"], v["code"], "EN-US", "Item", "Product", v["name"], v["name"],
            v["search"], v["item_group_id"] or "TES", "", "SWL", "No Batch",
            v["model_group_id"] or "FIFO_S_NQ", v["uom"], v["uom"], v["uom"], "",
            "GOODS", "", "Yes", "Yes",
        ])
        wms.append([v["code"], "", "", v["group_type_code"], v["name"], "", "YES", "YES"])
    _sheet(wb, "CBD_ReleasedProduct_Template_RE", CBD_HEADERS, main)
    _sheet(wb, "CBG_ItemWMSsetupEntity",
           ["ITEMID", "INVENTCOLORID", "COLORNAME", "GROUPTYPECODE", "ITEMNAME",
            "MEMO", "PR", "SPAREPART"], wms)
    return wb


# --- APM / APG: 5-sheet D365 entity import ----------------------------------
def _build_d365_multi(db, requests, site: str, warehouse: str):
    wb = Workbook()
    products, released, categories, orders, wms = [], [], [], [], []
    for req in requests:
        v = _resolve(db, req)
        products.append([v["code"], v["name"], v["name"], v["search"], "Product",
                         v["product_type"]])
        released.append([
            v["code"], "", "", "", "---", "", "", v["uom"], "Yes", "Yes", "Yes",
            v["model_group_id"] or "EN", "", "", v["item_group_id"] or "EN-FS", "None",
            v["code"], "Product", v["price"], "", "DUE", v["uom"], "", "DUE", v["uom"],
            v["search"], "", "Service" if v["product_type"] == "Service" else "STOCK",
            "None" if v["product_type"] == "Service" else "NONE", "", "NONE",
        ])
        categories.append([v["code"], v["category"], "Procurement Category"])
        orders.append([
            v["code"], ".000000", site, warehouse, "false", "No", "No", "No", "No",
            "No", "No", "No", "No", "false", "No", "No", "No", "No", ".000000",
            ".000000", ".000000", ".000000", ".000000", ".000000", "", ".000000",
            site, warehouse, site, warehouse,
        ])
        wms.append([v["code"], "", "", v["group_type_code"], v["name"], "", "Yes", "Yes"])
    _sheet(wb, "Products_V2",
           ["PRODUCTNUMBER", "PRODUCTDESCRIPTION", "PRODUCTNAME", "PRODUCTSEARCHNAME",
            "PRODUCTSUBTYPE", "PRODUCTTYPE"], products)
    _sheet(wb, "Released_products_V2", [
        "ITEMNUMBER", "BATCHNUMBERGROUPCODE", "BOMUNITSYMBOL", "COSTGROUPID",
        "DEFAULTLEDGERDIMENSIONDISPLAYVALUE", "FLUSHINGPRINCIPLE",
        "INVENTORYRESERVATIONHIERARCHYNAME", "INVENTORYUNITSYMBOL",
        "ISPURCHASEPRICEAUTOMATICALLYUPDATED", "ISUNITCOSTAUTOMATICALLYUPDATED",
        "ISUNITCOSTINCLUDINGCHARGES", "ITEMMODELGROUPID", "PHYSICALDIMENSIONGROUPID",
        "PRODUCTCOVERAGEGROUPID", "PRODUCTGROUPID", "PRODUCTIONTYPE", "PRODUCTNUMBER",
        "PRODUCTSUBTYPE", "PURCHASEPRICE", "PURCHASEPRICEDATE",
        "PURCHASESALESTAXITEMGROUPCODE", "PURCHASEUNITSYMBOL",
        "RAWMATERIALPICKINGPRINCIPLE", "SALESSALESTAXITEMGROUPCODE", "SALESUNITSYMBOL",
        "SEARCHNAME", "SHELFLIFEPERIODDAYS", "STORAGEDIMENSIONGROUPNAME",
        "TRACKINGDIMENSIONGROUPNAME", "UNITCONVERSIONSEQUENCEGROUPID", "UNITCOST",
    ], released)
    _sheet(wb, "Product_category_assignments",
           ["PRODUCTNUMBER", "PRODUCTCATEGORYNAME", "PRODUCTCATEGORYHIERARCHYNAME"],
           categories)
    _sheet(wb, "Default_order_settings", [
        "ITEMNUMBER", "INVENTORYQUANTITYMULTIPLES", "INVENTORYSITEID",
        "INVENTWAREHOUSEID", "ISINVENTORYATPINCLUDINGPLANNEDORDERS",
        "ISINVENTORYPROCESSINGSTOPPED", "ISINVENTORYSITEMANDATORY",
        "ISINVENTORYUSINGWORKINGDAYS", "ISINVENTORYWAREHOUSEMANDATORY",
        "ISPROCUREMENTPROCESSINGSTOPPED", "ISPROCUREMENTSITEMANDATORY",
        "ISPROCUREMENTUSINGWORKINGDAYS", "ISPROCUREMENTWAREHOUSEMANDATORY",
        "ISSALESATPINCLUDINGPLANNEDORDERS", "ISSALESLEADTIMEOVERRIDDEN",
        "ISSALESPROCESSINGSTOPPED", "ISSALESSITEMANDATORY", "ISSALESWAREHOUSEMANDATORY",
        "MAXIMUMINVENTORYORDERQUANTITY", "MAXIMUMPROCUREMENTORDERQUANTITY",
        "MAXIMUMSALESORDERQUANTITY", "MINIMUMINVENTORYORDERQUANTITY",
        "MINIMUMPROCUREMENTORDERQUANTITY", "MINIMUMSALESORDERQUANTITY",
        "PROCUREMENTLEADTIMEDAYS", "PROCUREMENTQUANTITYMULTIPLES", "PROCUREMENTSITEID",
        "PROCUREMENTWAREHOUSEID", "SALESSITEID", "SALESWAREHOUSEID",
    ], orders)
    _sheet(wb, "CBG_ItemWMSsetupEntity",
           ["ITEMID", "INVENTCOLORID", "COLORNAME", "GROUPTYPECODE", "ITEMNAME",
            "MEMO", "PR", "SPAREPART"], wms)
    return wb


# --- ACM: one wide sheet + procurement category + WMS -----------------------
ACM_HEADERS = [
    "ItemId", "DisplayProductNumber", "ProductSubType",
    "EcoResProductTranslation_LanguageId", "EcoResProductTranslation_Name", "NameAlias",
    "SearchName", "ItemGroupId", "PrimaryVendorId", "ProdFlushingPrincip", "CostGroupId",
    "PdsShelfLife", "PdsShelfAdvice", "ITEMTYPE", "ProductType", "PmfProductType",
    "Phantom", "PmfYieldPct", "DefaultOrderType", "ModelGroupId",
    "EcoResStorageDimensionGroup_Name", "EcoResTrackingDimensionGroup_Name", "ReqGroupId",
    "BatchNumGroupId", "PURCHMODEL", "COSTMODEL", "InventTableModuleSales_TaxItemGroupID",
    "InventTableModuleInvent_Price", "InventTableModuleInvent_PriceUnit",
    "InventTableModuleInvent_UnitID", "InventTableModuleInvent_EndDisc",
    "InventTableModuleInvent_TaxItemGroupID", "InventTableModulePurch_Price",
    "InventTableModuleInvent_PriceQTY", "InventTableModulePurch_PriceUnit",
    "InventTableModulePurch_UnitID", "InventTableModulePurch_EndDisc",
    "InventTableModulePurch_TaxItemGroupID", "InventTableModulePurch_PriceQTY",
    "InventTableModuleSales_Price", "InventTableModuleSales_PriceUnit",
    "InventTableModuleSales_UnitID", "InventTableModuleSales_EndDisc",
    "InventTableModuleSales_PriceQTY", "ItemBuyerGroupId", "BOMUnitId", "NetWeight",
    "TaraWeight", "UOMSeqGroupId", "MaxPickQty", "PackSizeCateogryId", "PhysDimId",
    "WHSReservationHierarchy_Name", "FilterCode", "IVZ_UseTransportationMgmt_CT",
]


def _build_acm(db, requests):
    wb = Workbook()
    main, cats, wms = [], [], []
    for req in requests:
        v = _resolve(db, req)
        u = v["uom"]
        main.append([
            v["code"], v["code"], "Product", "EN-SG", v["name"], v["name"], v["search"],
            v["item_group_id"] or "SERVICE", "", "Manual", "", "0", "0", "Item",
            v["product_type"], "None", "", "0", "0", v["model_group_id"] or "SERVICE",
            "STOCK", "NONE", "Manual", "", "Yes", "Yes", "DUE", "", "1", u, "1", "DUE",
            v["price"], "", "1", u, "", "DUE", "", "0", "1", u, "", "", "", u, "", "",
            u, "", "", "SWL", "NONE", v["item_group_id"] or "SERVICE", "",
        ])
        cats.append([v["category"], "ProcurementCategory", v["code"]])
        wms.append([v["code"], "", "", v["group_type_code"], v["name"],
                    "Opex/Spare Part", "YES", "YES"])
    _sheet(wb, "ACM - Item Update", ACM_HEADERS, main)
    _sheet(wb, "ACM Purecument Category",
           ["EcoResCategory_Name", "EcoResCategoryHierarchy_Name",
            "Product_DisplayProductNumber"], cats)
    _sheet(wb, "CBG_ItemWMSsetupEntity",
           ["ITEMID", "INVENTCOLORID", "COLORNAME", "GROUPTYPECODE", "ITEMNAME",
            "MEMO", "PR", "SPAREPART"], wms)
    return wb


BUILDERS = {
    "CBD": lambda db, rs: _build_cbd(db, rs),
    "APM": lambda db, rs: _build_d365_multi(db, rs, "APM", ""),
    "APG": lambda db, rs: _build_d365_multi(db, rs, "APG", "SPP"),
    "ACM": lambda db, rs: _build_acm(db, rs),
}


def build_workbook_bytes(db: Session, factory_code: str, requests: list[ItemRequest]) -> bytes:
    builder = BUILDERS.get(factory_code)
    if builder is None:
        raise ExportError(f"ยังไม่รองรับ format ของโรงงาน {factory_code}")
    wb = builder(db, requests)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_pending(db: Session, factory_id: int, *, account: Account) -> ExportBatch:
    """Export all approved-but-not-exported requests for a factory into one file."""
    from datetime import datetime

    from app.models import Factory, RequestEvent

    factory = db.get(Factory, factory_id)
    if factory is None:
        raise ExportError("ไม่พบโรงงาน")
    # Lock the rows (Postgres) so a concurrent re-categorise or code override
    # cannot change a code between this read and the export commit; see
    # requests._get_locked for the other side.
    locked = db.scalars(
        select(ItemRequest)
        .where(
            ItemRequest.factory_id == factory_id,
            ItemRequest.status == "approved",
            ItemRequest.export_batch_id.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Re-check after the lock: a row may have changed while we waited for it.
    reqs = [r for r in locked if r.status == "approved" and r.export_batch_id is None]
    if not reqs:
        raise ExportError("ไม่มีคำขอที่อนุมัติแล้วรอ export สำหรับโรงงานนี้")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{FILENAME_HINT.get(factory.code, factory.code)}_{ts}.xlsx"
    batch = ExportBatch(
        factory_id=factory_id, filename=filename, item_count=len(reqs),
        created_by=account.email,
    )
    db.add(batch)
    db.flush()
    for req in reqs:
        req.status = "exported"
        req.export_batch_id = batch.id
        db.add(RequestEvent(request_id=req.id, actor=account.email, action="exported",
                            detail=filename))
    db.commit()
    return batch
