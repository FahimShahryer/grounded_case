from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.tables import Case
from app.models.case import CaseCreate, CaseOut

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("", response_model=CaseOut, status_code=201)
async def create_case(payload: CaseCreate, session: SessionDep) -> Case:
    existing = await session.execute(
        select(Case).where(Case.case_number == payload.case_number)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Case {payload.case_number} already exists.",
        )

    case = Case(
        case_number=payload.case_number,
        borrower=payload.borrower,
        property_address=payload.property_address,
        county=payload.county,
        state=payload.state,
        servicer=payload.servicer,
        loan_number=payload.loan_number,
        loan_amount=payload.loan_amount,
        loan_date=payload.loan_date,
        default_date=payload.default_date,
        current_status=payload.current_status,
        notes=payload.notes,
        context=payload.context,
    )
    session.add(case)
    await session.commit()
    await session.refresh(case)
    return case


@router.get("", response_model=list[CaseOut])
async def list_cases(session: SessionDep) -> list[Case]:
    result = await session.execute(select(Case).order_by(Case.id))
    return list(result.scalars())


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(case_id: int, session: SessionDep) -> Case:
    case = await session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
