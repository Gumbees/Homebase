import uuid
from datetime import datetime, timedelta
from sqlalchemy.dialects.postgresql import JSONB, BYTEA
from app import db

# Association table for the many-to-many relationship between objects and categories
object_categories = db.Table('object_categories',
    db.Column('object_id', db.Integer, db.ForeignKey('objects.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('categories.id'), primary_key=True),
    db.Column('added_at', db.DateTime, default=datetime.utcnow)
)

class Vendor(db.Model):
    __tablename__ = 'vendors'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    contact_info = db.Column(JSONB)  # Store email, phone, address, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    needs_approval = db.Column(db.Boolean, default=False)  # Flag for approval queue
    approved_at = db.Column(db.DateTime, nullable=True)  # When the vendor was approved
    
    # Relationships
    invoices = db.relationship('Invoice', backref='vendor', lazy='dynamic')
    
    def __repr__(self):
        return f"<Vendor {self.name}>"

class Invoice(db.Model):
    __tablename__ = 'invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True)  # Optional reference to vendor
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_paid = db.Column(db.Boolean, default=True)  # Marked as paid for receipts automatically
    data = db.Column(JSONB, nullable=False)  # JSON document format for flexible data storage
    
    # Relationships
    line_items = db.relationship('InvoiceLineItem', backref='invoice', cascade="all, delete-orphan")
    attachments = db.relationship('Attachment', backref='invoice', cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Invoice {self.invoice_number}>"
    
    @staticmethod
    def generate_invoice_number():
        """Generate a unique invoice number"""
        prefix = "INV"
        random_part = str(uuid.uuid4().hex)[:8].upper()
        date_part = datetime.utcnow().strftime("%Y%m%d")
        return f"{prefix}-{date_part}-{random_part}"

class InvoiceLineItem(db.Model):
    __tablename__ = 'invoice_line_items'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    data = db.Column(JSONB, nullable=False)  # JSON document format for flexible line item data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<InvoiceLineItem {self.id}>"

class Attachment(db.Model):
    __tablename__ = 'attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_data = db.Column(BYTEA, nullable=False)  # Binary data for the receipt
    file_type = db.Column(db.String(100))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<Attachment {self.filename}>"

class Object(db.Model):
    __tablename__ = 'objects'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)  # Optional, objects can exist without a receipt
    object_type = db.Column(db.String(50), nullable=False, index=True)  # 'asset', 'consumable', 'component', 'person', 'pet', 'other'
    data = db.Column(JSONB, nullable=False)  # JSON document format for object details
    parent_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=True)  # For components that are part of assets
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Re-evaluation tracking fields
    last_evaluated_at = db.Column(db.DateTime, nullable=True)  # When the object was last re-evaluated by AI
    next_evaluation_date = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=90))  # When to next re-evaluate
    evaluation_confidence = db.Column(db.Float, nullable=True)  # Confidence level of the last evaluation (0.0-1.0)
    needs_manual_review = db.Column(db.Boolean, default=False)  # Flag for manual approval queue
    ai_evaluation_pending = db.Column(db.Boolean, default=False)  # Flag for AI evaluation queue
    evaluation_history = db.Column(JSONB, default=lambda: [])  # List of previous evaluations
    
    # Self-referential relationship for components
    children = db.relationship('Object', backref=db.backref('parent', remote_side=[id]), 
                               cascade="all, delete-orphan")
    
    # For person-pet relationships (many-to-many)
    person_pet_associations = db.relationship('PersonPetAssociation', 
                                              foreign_keys='PersonPetAssociation.object_id',
                                              backref='object', cascade="all, delete-orphan")
    
    # Relationship to AI evaluation queue entries
    ai_queue_entries = db.relationship('AIEvaluationQueue', backref='object', lazy='dynamic',
                                       cascade="all, delete-orphan")
                                       
    # Relationship to object attachments (photos, documents, etc.)
    attachments = db.relationship('ObjectAttachment', backref='object', lazy='dynamic',
                                  cascade="all, delete-orphan")
                                  
    # Relationship to categories (many-to-many)
    categories = db.relationship('Category', secondary=object_categories,
                                 lazy='dynamic', backref=db.backref('objects', lazy='dynamic'))
    
    def __repr__(self):
        object_name = self.data.get('name', 'Unnamed')
        return f"<{self.object_type.capitalize()} '{object_name}' ({self.id})>"
    
    @property
    def is_asset(self):
        return self.object_type == 'asset'
    
    @property
    def is_consumable(self):
        return self.object_type == 'consumable'
    
    @property
    def is_component(self):
        return self.object_type == 'component'
    
    @property
    def is_person(self):
        return self.object_type == 'person'
    
    @property
    def is_pet(self):
        return self.object_type == 'pet'
    
    @property
    def is_service(self):
        return self.object_type == 'service'
    
    @property
    def is_software(self):
        return self.object_type == 'software'
    
    @property
    def name(self):
        return self.data.get('name', 'Unnamed')
    
    @property
    def description(self):
        return self.data.get('description', '')
    
    def schedule_evaluation(self, days_from_now=90):
        """
        Schedule this object for AI re-evaluation in the specified number of days.
        
        Args:
            days_from_now: Number of days from now to schedule the evaluation
            
        Returns:
            datetime: The scheduled evaluation date
        """
        # Set the next evaluation date
        self.next_evaluation_date = datetime.utcnow() + timedelta(days=days_from_now)
        
        # Clear any manual review flag
        if self.needs_manual_review:
            self.needs_manual_review = False
            
        # Update the object
        self.updated_at = datetime.utcnow()
        
        return self.next_evaluation_date
    
    def record_evaluation(self, evaluation_result, confidence=None):
        """
        Record an AI evaluation result in the object's history and update fields
        
        Args:
            evaluation_result: Dictionary with evaluation results
            confidence: Confidence score (0.0-1.0), if not included in evaluation_result
            
        Returns:
            dict: The evaluation record that was added to history
        """
        # Extract confidence if provided in the result
        if confidence is None and 'confidence' in evaluation_result:
            confidence = float(evaluation_result['confidence'])
        
        # Default confidence if still not set
        if confidence is None:
            confidence = 0.7
            
        # Create evaluation record
        evaluation_record = {
            'date': datetime.utcnow().isoformat(),
            'result': evaluation_result,
            'confidence': confidence,
            'approved': confidence >= 0.8 if confidence is not None else True
        }
        
        # Initialize history if not exists
        if not self.evaluation_history:
            self.evaluation_history = []
        
        # Add new evaluation to history
        history_list = self.evaluation_history.copy()
        history_list.append(evaluation_record)
        self.evaluation_history = history_list
        
        # Update evaluation metadata
        self.last_evaluated_at = datetime.utcnow()
        self.evaluation_confidence = confidence
        self.ai_evaluation_pending = False
        
        # Flag for manual review if confidence is below threshold
        if confidence is not None and confidence < 0.8:
            self.needs_manual_review = True
        else:
            self.needs_manual_review = False
        
        # Update the object
        self.updated_at = datetime.utcnow()
        
        return evaluation_record

# Association table for person-pet relationship (many-to-many)
class PersonPetAssociation(db.Model):
    __tablename__ = 'person_pet_associations'
    
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=False)
    object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=False)
    relationship_type = db.Column(db.String(50), default='owner')  # 'owner', 'caretaker', etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships (from the other side)
    person = db.relationship('Object', foreign_keys=[person_id], backref='pet_associations')
    
    def __repr__(self):
        return f"<PersonPetAssociation {self.relationship_type}>"

class ObjectAttachment(db.Model):
    """
    Attachments specifically for Objects (separate from invoice attachments).
    This allows objects to have multiple photos and documents for AI analysis.
    """
    __tablename__ = 'object_attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_data = db.Column(BYTEA, nullable=False)  # Binary data for the attachment
    file_type = db.Column(db.String(100))  # MIME type of the file
    attachment_type = db.Column(db.String(50), default='photo')  # photo, document, etc.
    description = db.Column(db.String(255))  # Optional description of the attachment
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    ai_analyzed = db.Column(db.Boolean, default=False)  # Whether this attachment has been analyzed by AI
    ai_analysis_result = db.Column(JSONB, nullable=True)  # Results of AI analysis
    
    def __repr__(self):
        return f"<ObjectAttachment {self.filename} for Object {self.object_id}>"

class Category(db.Model):
    """
    Categories for objects, organized by object type.
    Categories can be suggested by AI during object evaluation.
    """
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    object_type = db.Column(db.String(50), nullable=False, index=True)
    description = db.Column(db.String(255))
    icon = db.Column(db.String(50))  # FontAwesome icon name
    color = db.Column(db.String(20))  # CSS color code or class
    is_default = db.Column(db.Boolean, default=False)  # Whether this is a system default category
    confidence_score = db.Column(db.Float, default=0.8)  # AI confidence score (default to high for manual entries)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('name', 'object_type', name='unique_category_per_type'),)
    
    def __repr__(self):
        return f"<Category {self.name} ({self.object_type})>"
    
    @classmethod
    def get_categories_for_type(cls, object_type):
        """Get all categories for a specific object type"""
        return cls.query.filter_by(object_type=object_type).order_by(cls.name).all()
    
    @classmethod
    def get_or_create(cls, name, object_type, description=None, icon=None, color=None, confidence_score=None):
        """
        Get an existing category or create a new one if it doesn't exist.
        If an existing category is found but has a lower confidence score than the new one,
        update its attributes with the new values.
        
        Returns:
            Category: The retrieved or created category
            bool: True if created, False if retrieved
        """
        # Normalize name by capitalizing and trimming
        normalized_name = name.strip().capitalize()
        
        # Check if category already exists
        category = cls.query.filter_by(name=normalized_name, object_type=object_type).first()
        
        if category:
            # Category exists, check if we should update it with new confidence
            if confidence_score and confidence_score > category.confidence_score:
                category.description = description or category.description
                category.icon = icon or category.icon
                category.color = color or category.color
                category.confidence_score = confidence_score
                category.updated_at = datetime.utcnow()
                db.session.commit()
            return category, False
        
        # Create new category
        new_category = cls(
            name=normalized_name,
            object_type=object_type,
            description=description,
            icon=icon,
            color=color,
            confidence_score=confidence_score or 0.8  # Default confidence if not provided
        )
        
        db.session.add(new_category)
        db.session.commit()
        
        return new_category, True

class AIEvaluationQueue(db.Model):
    """
    Queue for AI evaluation of objects.
    Objects are scheduled for re-evaluation every 90 days.
    This queue manages the process and rate limits to 30 evaluations per day.
    """
    __tablename__ = 'ai_evaluation_queue'
    
    id = db.Column(db.Integer, primary_key=True)
    object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=False)
    scheduled_date = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, failed
    last_attempt = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0)
    result = db.Column(JSONB, nullable=True)  # Result of the evaluation
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f"<AIEvaluationQueue {self.object_id} ({self.status})>"
    
    @staticmethod
    def get_daily_queue(date=None, limit=30):
        """
        Get the queue for a specific date, limited to a maximum number of items.
        If no date is provided, defaults to today.
        """
        if date is None:
            date = datetime.utcnow().date()
        
        # Convert date to datetime for comparison
        day_start = datetime.combine(date, datetime.min.time())
        day_end = datetime.combine(date, datetime.max.time())
        
        # Get the queue for the day, prioritizing oldest objects first
        return AIEvaluationQueue.query.filter(
            AIEvaluationQueue.scheduled_date.between(day_start, day_end),
            AIEvaluationQueue.status == 'pending'
        ).order_by(AIEvaluationQueue.scheduled_date).limit(limit).all()
    
    @staticmethod
    def schedule_object(object_id, scheduled_date=None):
        """
        Schedule an object for AI evaluation.
        """
        if scheduled_date is None:
            # Schedule for today by default, actual processing depends on queue availability
            scheduled_date = datetime.utcnow()
        
        # Check if already in queue
        existing = AIEvaluationQueue.query.filter_by(
            object_id=object_id,
            status='pending'
        ).first()
        
        if existing:
            # Update existing queue entry
            existing.scheduled_date = scheduled_date
            return existing
        
        # Create new queue entry
        queue_entry = AIEvaluationQueue(
            object_id=object_id,
            scheduled_date=scheduled_date
        )
        
        # Update object status
        obj = Object.query.get(object_id)
        if obj:
            obj.ai_evaluation_pending = True
        
        db.session.add(queue_entry)
        return queue_entry
    
    @staticmethod
    def count_pending_for_day(date=None):
        """
        Count pending evaluations for a specific day.
        """
        if date is None:
            date = datetime.utcnow().date()
            
        day_start = datetime.combine(date, datetime.min.time())
        day_end = datetime.combine(date, datetime.max.time())
        
        return AIEvaluationQueue.query.filter(
            AIEvaluationQueue.scheduled_date.between(day_start, day_end),
            AIEvaluationQueue.status == 'pending'
        ).count()
    
    @staticmethod
    def count_completed_for_day(date=None):
        """
        Count completed evaluations for a specific day.
        """
        if date is None:
            date = datetime.utcnow().date()
            
        day_start = datetime.combine(date, datetime.min.time())
        day_end = datetime.combine(date, datetime.max.time())
        
        return AIEvaluationQueue.query.filter(
            AIEvaluationQueue.completed_at.between(day_start, day_end),
            AIEvaluationQueue.status == 'completed'
        ).count()
    
    @staticmethod
    def find_objects_due_for_evaluation():
        """
        Find objects that are due for re-evaluation but not yet in the queue.
        """
        now = datetime.utcnow()
        
        # Find objects that are due for evaluation
        due_objects = Object.query.filter(
            Object.next_evaluation_date <= now,
            Object.ai_evaluation_pending == False
        ).all()
        
        return due_objects
    
    @staticmethod
    def schedule_evaluations():
        """
        Schedule objects for evaluation that are due.
        This function is meant to be called daily by a scheduler.
        """
        due_objects = AIEvaluationQueue.find_objects_due_for_evaluation()
        scheduled_count = 0
        
        # Get current date
        today = datetime.utcnow().date()
        
        # Check how many slots are available today
        pending_count = AIEvaluationQueue.count_pending_for_day(today)
        completed_count = AIEvaluationQueue.count_completed_for_day(today)
        daily_limit = 30
        available_slots = max(0, daily_limit - (pending_count + completed_count))
        
        # Schedule objects up to the available slot limit
        for obj in due_objects[:available_slots]:
            AIEvaluationQueue.schedule_object(obj.id)
            scheduled_count += 1
        
        # For objects beyond today's limit, schedule for future days
        if len(due_objects) > available_slots:
            days_ahead = 1
            for obj in due_objects[available_slots:]:
                # Keep advancing days until we find a day with an open slot
                while True:
                    future_date = today + timedelta(days=days_ahead)
                    pending_for_day = AIEvaluationQueue.count_pending_for_day(future_date)
                    
                    if pending_for_day < daily_limit:
                        # This day has an available slot
                        scheduled_date = datetime.combine(future_date, datetime.min.time())
                        AIEvaluationQueue.schedule_object(obj.id, scheduled_date)
                        scheduled_count += 1
                        break
                    
                    days_ahead += 1
                    
                    # Safety limit to prevent infinite loop
                    if days_ahead > 365:
                        break
        
        return scheduled_count

class AISettings(db.Model):
    """
    Settings for AI providers and models.
    Allows configuring multiple AI providers including commercial services (OpenAI, Anthropic)
    and local models via LLM Studio.
    """
    __tablename__ = 'ai_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False, unique=True)  # openai, anthropic, llm_studio
    is_enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    api_key = db.Column(db.String(255), nullable=True)  # Encrypted or masked in UI
    api_endpoint = db.Column(db.String(255), nullable=True)  # For custom endpoints like LLM Studio
    config = db.Column(JSONB, nullable=False, default=lambda: {})  # JSON config for specific provider
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<AISettings {self.provider} ({'enabled' if self.is_enabled else 'disabled'})>"
    
    @staticmethod
    def get_provider_config(provider_name):
        """
        Get configuration for a specific provider.
        
        Args:
            provider_name: Name of the provider (openai, anthropic, llm_studio)
            
        Returns:
            dict: Provider configuration or None if not found
        """
        provider = AISettings.query.filter_by(provider=provider_name).first()
        if not provider:
            return None
            
        # Return dict with all provider settings
        return {
            'id': provider.id,
            'provider': provider.provider,
            'is_enabled': provider.is_enabled,
            'is_default': provider.is_default,
            'api_key': provider.api_key,
            'api_endpoint': provider.api_endpoint,
            'config': provider.config or {}
        }
    
    @staticmethod
    def get_default_provider():
        """
        Get the default AI provider configuration.
        
        Returns:
            AISettings: Default provider settings or None if none is set
        """
        return AISettings.query.filter_by(is_default=True, is_enabled=True).first()
    
    @staticmethod
    def set_default_provider(provider_name):
        """
        Set a provider as the default.
        
        Args:
            provider_name: Name of the provider to set as default
            
        Returns:
            bool: Success status
        """
        # First, clear any existing default
        AISettings.query.filter_by(is_default=True).update({'is_default': False})
        
        # Set the new default
        provider = AISettings.query.filter_by(provider=provider_name).first()
        if not provider:
            return False
            
        provider.is_default = True
        db.session.commit()
        return True
    
    @classmethod
    def initialize_defaults(cls):
        """Initialize default AI provider settings."""
        defaults = [
            {
                "provider": "anthropic",
                "is_enabled": True,
                "is_default": True,
                "config": {
                    "default_model": "claude-3-5-sonnet-20241022",
                    "vision_model": "claude-3-opus-20240229",
                    "timeout": 180
                }
            },
            # ...other providers...
        ]
        
        for default in defaults:
            # Check if provider already exists
            existing = cls.query.filter_by(provider=default["provider"]).first()
            if not existing:
                provider = cls(**default)
                db.session.add(provider)
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

class TaskQueue(db.Model):
    """
    Task queue for asynchronous processing.
    Used for automated tasks such as consumable expiration tracking,
    inventory stock checks, and other scheduled maintenance.
    """
    __tablename__ = 'task_queue'
    
    id = db.Column(db.Integer, primary_key=True)
    task_type = db.Column(db.String(50), nullable=False, index=True)  # consumable_expiration, stock_check, etc.
    object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=True)  # Optional reference to an object
    execute_at = db.Column(db.DateTime, nullable=False, index=True)  # When to execute this task
    status = db.Column(db.String(20), default='pending', index=True)  # pending, processing, completed, failed
    priority = db.Column(db.Integer, default=1)  # 1-10, higher values are processed first
    data = db.Column(JSONB, nullable=False, default=lambda: {})  # Task-specific data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_attempt = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0)
    completed_at = db.Column(db.DateTime, nullable=True)
    result = db.Column(JSONB, nullable=True)  # Result of the task
    error_message = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f"<TaskQueue {self.id} ({self.task_type}, {self.status})>"
    
    @staticmethod
    def queue_task(task_data):
        """
        Add a new task to the queue
        
        Args:
            task_data: Dictionary with task details
                - task_type: Type of task (required)
                - object_id: ID of related object (optional)
                - execute_at: When to execute the task (required)
                - priority: 1-10, higher is processed first (optional)
                - data: Task-specific data (optional)
                
        Returns:
            TaskQueue: The created task
        """
        try:
            # Create new task
            task = TaskQueue(
                task_type=task_data['task_type'],
                object_id=task_data.get('object_id'),
                execute_at=task_data['execute_at'],
                priority=task_data.get('priority', 1),
                status=task_data.get('status', 'pending'),
                data=task_data.get('data', {})
            )
            
            db.session.add(task)
            db.session.commit()
            
            return task
            
        except Exception as e:
            db.session.rollback()
            raise e
    
    @staticmethod
    def schedule_consumable_expiration(object_id, expiration_date, quantity=1):
        """
        Schedule a consumable expiration task
        
        Args:
            object_id: ID of the consumable object
            expiration_date: When the consumable expires (date string or datetime)
            quantity: Quantity that will expire (default: 1)
            
        Returns:
            TaskQueue: The created task
        """
        # Convert string date to datetime if needed
        if isinstance(expiration_date, str):
            expiration_date = datetime.strptime(expiration_date, '%Y-%m-%d')
            
        # Get object info for data
        obj = Object.query.get(object_id)
        if not obj:
            raise ValueError(f"Object with ID {object_id} not found")
            
        # Create task data
        task_data = {
            'task_type': 'consumable_expiration',
            'object_id': object_id,
            'execute_at': expiration_date,
            'priority': 3,  # Medium priority
            'data': {
                'object_type': 'consumable',
                'name': obj.data.get('name', 'Unnamed Consumable'),
                'quantity': quantity
            }
        }
        
        return TaskQueue.queue_task(task_data)
    
    @staticmethod
    def get_pending_tasks(limit=100):
        """
        Get pending tasks that are ready to be processed,
        ordered by priority and scheduled time
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            list: List of TaskQueue objects
        """
        now = datetime.utcnow()
        
        return TaskQueue.query.filter(
            TaskQueue.status == 'pending',
            TaskQueue.execute_at <= now
        ).order_by(
            TaskQueue.priority.desc(),
            TaskQueue.execute_at
        ).limit(limit).all()


class Reminder(db.Model):
    """
    Reminders for various system actions.
    Includes shopping lists, maintenance tasks, and other notifications.
    """
    __tablename__ = 'reminders'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    reminder_type = db.Column(db.String(50), nullable=False, index=True)  # shopping_list, maintenance, etc.
    status = db.Column(db.String(20), default='open', index=True)  # open, completed
    priority = db.Column(db.Integer, default=1)  # 1-5, higher is more important
    due_date = db.Column(db.DateTime, nullable=True)
    completed_date = db.Column(db.DateTime, nullable=True)
    items = db.Column(JSONB, nullable=True)  # For checklists and shopping lists
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Reminder {self.id} ({self.title}, {self.status})>"
    
    def mark_complete(self):
        """Mark this reminder as completed"""
        self.status = 'completed'
        self.completed_date = datetime.utcnow()
        db.session.commit()
        return self
    
    @staticmethod
    def get_open_reminders(reminder_type=None):
        """
        Get all open reminders, optionally filtered by type
        
        Args:
            reminder_type: Optional type filter
            
        Returns:
            list: List of open Reminder objects
        """
        query = Reminder.query.filter_by(status='open')
        
        if reminder_type:
            query = query.filter_by(reminder_type=reminder_type)
            
        return query.order_by(
            Reminder.priority.desc(),
            Reminder.due_date
        ).all()

# ============================================================================
# ENTITY MODELS - Information/Administrative Records
# ============================================================================

class Organization(db.Model):
    """
    Organizations are entities that represent business relationships.
    This replaces the simpler Vendor model with a more comprehensive system
    for managing any type of organization: vendors, service providers, clients, etc.
    """
    __tablename__ = 'organizations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    organization_type = db.Column(db.String(50), default='vendor', index=True)  # vendor, client, service_provider, etc.
    data = db.Column(JSONB, nullable=False, default=lambda: {})  # Flexible storage for all org data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, index=True)
    needs_approval = db.Column(db.Boolean, default=False)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    # invoices = db.relationship('Invoice', backref='organization', lazy='dynamic',
    #                            primaryjoin="Organization.id == foreign(Invoice.data['organization_id'].astext.cast(Integer))",
    #                            overlaps="vendor")
    contacts = db.relationship('OrganizationContact', backref='organization', lazy='dynamic',
                               cascade="all, delete-orphan")
    notes = db.relationship('Note', backref='organization', lazy='dynamic')
    calendar_events = db.relationship('CalendarEvent', backref='organization', lazy='dynamic')
    
    def __repr__(self):
        return f"<Organization {self.name} ({self.organization_type})>"
    
    @property
    def contact_info(self):
        """Get contact information from data JSON"""
        return self.data.get('contact_info', {})
    
    @property
    def address(self):
        """Get address from data JSON"""
        return self.data.get('address', '')
    
    @property
    def phone(self):
        """Get phone from data JSON"""
        return self.data.get('phone', '')
    
    @property
    def email(self):
        """Get email from data JSON"""
        return self.data.get('email', '')
    
    @property
    def website(self):
        """Get website from data JSON"""
        return self.data.get('website', '')
    
    @classmethod
    def get_or_create(cls, name, organization_type='vendor', **kwargs):
        """Get an existing organization or create a new one"""
        org = cls.query.filter_by(name=name).first()
        if not org:
            org = cls(name=name, organization_type=organization_type, **kwargs)
            db.session.add(org)
            db.session.commit()
        return org

class OrganizationRelationship(db.Model):
    """
    Many-to-many relationships between organizations with labeled relationship types.
    Supports complex business relationships like parent/subsidiary, partnerships, franchises, etc.
    """
    __tablename__ = 'organization_relationships'
    
    id = db.Column(db.Integer, primary_key=True)
    from_organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    to_organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    relationship_type = db.Column(db.String(50), nullable=False, index=True)  # 'parent', 'subsidiary', 'partner', 'franchise', etc.
    relationship_label = db.Column(db.String(100))  # Custom description like "Parent Company", "Regional Franchise"
    is_bidirectional = db.Column(db.Boolean, default=False)  # Whether relationship works both ways
    strength = db.Column(db.Integer, default=5)  # 1-10 strength of relationship
    relationship_metadata = db.Column(JSONB, default=lambda: {})  # Additional relationship data
    start_date = db.Column(db.DateTime, nullable=True)  # When relationship started
    end_date = db.Column(db.DateTime, nullable=True)  # When relationship ended (for historical tracking)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    from_organization = db.relationship('Organization', foreign_keys=[from_organization_id],
                                        backref='outgoing_relationships')
    to_organization = db.relationship('Organization', foreign_keys=[to_organization_id],
                                      backref='incoming_relationships')
    
    # Unique constraint to prevent duplicate relationships
    __table_args__ = (
        db.UniqueConstraint('from_organization_id', 'to_organization_id', 'relationship_type', 
                           name='unique_org_relationship'),
        db.CheckConstraint('from_organization_id != to_organization_id', 
                          name='no_self_relationship')
    )
    
    def __repr__(self):
        return f"<OrgRelationship {self.from_organization.name} -[{self.relationship_type}]-> {self.to_organization.name}>"
    
    @property
    def description(self):
        """Human-readable description of the relationship"""
        return self.relationship_label or f"{self.relationship_type.replace('_', ' ').title()}"
    
    @classmethod
    def create_relationship(cls, from_org_id, to_org_id, relationship_type, 
                           relationship_label=None, is_bidirectional=False, **kwargs):
        """
        Create a relationship between two organizations.
        Optionally creates the reverse relationship if bidirectional.
        """
        # Create primary relationship
        relationship = cls(
            from_organization_id=from_org_id,
            to_organization_id=to_org_id,
            relationship_type=relationship_type,
            relationship_label=relationship_label,
            is_bidirectional=is_bidirectional,
            **kwargs
        )
        db.session.add(relationship)
        
        # Create reverse relationship if bidirectional
        if is_bidirectional:
            # Determine reverse relationship type
            reverse_type = cls._get_reverse_relationship_type(relationship_type)
            reverse_label = cls._get_reverse_relationship_label(relationship_label, relationship_type)
            
            reverse_relationship = cls(
                from_organization_id=to_org_id,
                to_organization_id=from_org_id,
                relationship_type=reverse_type,
                relationship_label=reverse_label,
                is_bidirectional=True,
                **kwargs
            )
            db.session.add(reverse_relationship)
            
        db.session.commit()
        return relationship
    
    @staticmethod
    def _get_reverse_relationship_type(relationship_type):
        """Get the reverse relationship type for bidirectional relationships"""
        reverse_mapping = {
            'parent': 'subsidiary',
            'subsidiary': 'parent',
            'partner': 'partner',
            'franchise': 'franchisor',
            'franchisor': 'franchise',
            'supplier': 'customer',
            'customer': 'supplier',
            'division': 'parent',
            'joint_venture': 'joint_venture',
            'acquisition': 'acquired_by',
            'acquired_by': 'acquisition'
        }
        return reverse_mapping.get(relationship_type, relationship_type)
    
    @staticmethod
    def _get_reverse_relationship_label(original_label, relationship_type):
        """Generate reverse relationship label"""
        if original_label:
            return f"Reverse of: {original_label}"
        return OrganizationRelationship._get_reverse_relationship_type(relationship_type).replace('_', ' ').title()
    
    @classmethod
    def get_organization_network(cls, org_id, max_depth=3):
        """
        Get the complete network of relationships for an organization.
        Returns a nested structure showing all connected organizations.
        """
        visited = set()
        network = {}
        
        def _traverse(current_org_id, depth=0):
            if depth > max_depth or current_org_id in visited:
                return {}
            
            visited.add(current_org_id)
            
            # Get all relationships for this organization
            outgoing = cls.query.filter_by(from_organization_id=current_org_id, is_active=True).all()
            incoming = cls.query.filter_by(to_organization_id=current_org_id, is_active=True).all()
            
            org_network = {
                'organization_id': current_org_id,
                'outgoing_relationships': [],
                'incoming_relationships': []
            }
            
            # Process outgoing relationships
            for rel in outgoing:
                rel_data = {
                    'relationship_id': rel.id,
                    'to_organization_id': rel.to_organization_id,
                    'relationship_type': rel.relationship_type,
                    'relationship_label': rel.relationship_label,
                    'strength': rel.strength,
                    'connected_network': _traverse(rel.to_organization_id, depth + 1)
                }
                org_network['outgoing_relationships'].append(rel_data)
            
            # Process incoming relationships
            for rel in incoming:
                rel_data = {
                    'relationship_id': rel.id,
                    'from_organization_id': rel.from_organization_id,
                    'relationship_type': rel.relationship_type,
                    'relationship_label': rel.relationship_label,
                    'strength': rel.strength,
                    'connected_network': _traverse(rel.from_organization_id, depth + 1)
                }
                org_network['incoming_relationships'].append(rel_data)
            
            return org_network
        
        return _traverse(org_id)
    
    @classmethod
    def get_relationship_types(cls):
        """Get available relationship types"""
        return [
            {'value': 'parent', 'label': 'Parent Company', 'description': 'Parent organization that owns this one'},
            {'value': 'subsidiary', 'label': 'Subsidiary', 'description': 'Organization owned by this one'},
            {'value': 'partner', 'label': 'Business Partner', 'description': 'Strategic business partnership'},
            {'value': 'franchise', 'label': 'Franchise', 'description': 'Franchisee of this organization'},
            {'value': 'franchisor', 'label': 'Franchisor', 'description': 'Grants franchise rights'},
            {'value': 'supplier', 'label': 'Supplier', 'description': 'Provides goods or services'},
            {'value': 'customer', 'label': 'Customer', 'description': 'Receives goods or services'},
            {'value': 'division', 'label': 'Division', 'description': 'Business division or unit'},
            {'value': 'joint_venture', 'label': 'Joint Venture', 'description': 'Shared business entity'},
            {'value': 'acquisition', 'label': 'Acquisition', 'description': 'Organization acquired by this one'},
            {'value': 'acquired_by', 'label': 'Acquired By', 'description': 'This organization was acquired'},
            {'value': 'competitor', 'label': 'Competitor', 'description': 'Business competitor'},
            {'value': 'alliance', 'label': 'Strategic Alliance', 'description': 'Strategic business alliance'}
        ]

class User(db.Model):
    """
    Users are entities that represent system access and digital identity.
    Users can be linked to People objects to connect digital identity with physical persons.
    """
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))  # For future authentication
    data = db.Column(JSONB, nullable=False, default=lambda: {})  # Profile data, settings, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_admin = db.Column(db.Boolean, default=False)
    preferences = db.Column(JSONB, default=lambda: {})  # User preferences
    
    # Relationships
    person_mappings = db.relationship('UserPersonMapping', backref='user', lazy='dynamic',
                                      cascade="all, delete-orphan")
    notes = db.relationship('Note', backref='user', lazy='dynamic')
    calendar_events = db.relationship('CalendarEvent', backref='user', lazy='dynamic')
    collections = db.relationship('Collection', backref='user', lazy='dynamic',
                                  cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User {self.username}>"
    
    @property
    def display_name(self):
        """Get display name from data or fallback to username"""
        return self.data.get('display_name', self.username)
    
    @property
    def first_name(self):
        """Get first name from data"""
        return self.data.get('first_name', '')
    
    @property
    def last_name(self):
        """Get last name from data"""
        return self.data.get('last_name', '')
    
    @property
    def primary_person(self):
        """Get the primary Person object linked to this user"""
        mapping = self.person_mappings.filter_by(is_primary=True).first()
        return mapping.person_object if mapping else None

class OrganizationContact(db.Model):
    """
    Links Organizations to People objects, representing contacts within organizations.
    """
    __tablename__ = 'organization_contacts'
    
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    person_object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=False)
    contact_type = db.Column(db.String(50), default='primary')  # primary, billing, technical, etc.
    relationship = db.Column(db.String(100))  # job title, role, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    person_object = db.relationship('Object', backref='organization_contacts')
    
    __table_args__ = (db.UniqueConstraint('organization_id', 'person_object_id', 'contact_type'),)
    
    def __repr__(self):
        return f"<OrganizationContact {self.contact_type}>"

class UserPersonMapping(db.Model):
    """
    Links Users to their corresponding People objects.
    Connects digital identity (User) with physical person (People Object).
    """
    __tablename__ = 'user_person_mapping'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    person_object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_primary = db.Column(db.Boolean, default=True)
    
    # Relationships
    person_object = db.relationship('Object', backref='user_mappings')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'person_object_id'),)
    
    def __repr__(self):
        return f"<UserPersonMapping User {self.user_id} -> Person {self.person_object_id}>"

class Note(db.Model):
    """
    Notes are entities for documentation and comments.
    Can be attached to Objects, Organizations, or standalone.
    """
    __tablename__ = 'notes'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text)
    note_type = db.Column(db.String(50), default='general', index=True)  # maintenance, warranty, etc.
    object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    data = db.Column(JSONB, default=lambda: {})  # Additional metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_private = db.Column(db.Boolean, default=False)
    
    # Relationships
    object = db.relationship('Object', backref='notes')
    
    def __repr__(self):
        return f"<Note {self.title}>"

class CalendarEvent(db.Model):
    """
    Calendar events are entities for scheduled activities.
    Can be linked to Objects (maintenance) or Organizations (meetings).
    """
    __tablename__ = 'calendar_events'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    event_type = db.Column(db.String(50), default='maintenance', index=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)  # Matches existing DB schema
    end_time = db.Column(db.DateTime, nullable=True)
    object_id = db.Column(db.Integer, db.ForeignKey('objects.id'), nullable=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    data = db.Column(JSONB, default=lambda: {})  # Matches existing DB schema (not event_metadata)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_completed = db.Column(db.Boolean, default=False, index=True)
    
    # Relationships
    object = db.relationship('Object', backref='calendar_events')
    
    def __repr__(self):
        return f"<CalendarEvent {self.title}>"
    
    # Property aliases for backward compatibility
    @property
    def event_date(self):
        """Alias for start_time for backward compatibility"""
        return self.start_time
    
    @event_date.setter
    def event_date(self, value):
        """Setter for event_date that updates start_time"""
        self.start_time = value
    
    @property
    def event_metadata(self):
        """Alias for data for backward compatibility"""
        return self.data
    
    @event_metadata.setter
    def event_metadata(self, value):
        """Setter for event_metadata that updates data"""
        self.data = value
    
    @property
    def location(self):
        """Get location from data JSON"""
        return self.data.get('location', '') if self.data else ''
    
    @location.setter
    def location(self, value):
        """Set location in data JSON"""
        if not self.data:
            self.data = {}
        self.data['location'] = value

# Association table for collection-object relationships
collection_objects = db.Table('collection_objects',
    db.Column('id', db.Integer, primary_key=True),
    db.Column('collection_id', db.Integer, db.ForeignKey('collections.id')),
    db.Column('object_id', db.Integer, db.ForeignKey('objects.id')),
    db.Column('added_at', db.DateTime, default=datetime.utcnow),
    db.UniqueConstraint('collection_id', 'object_id')
)

class Collection(db.Model):
    """
    Collections are entities for organizing and grouping Objects.
    Users can create custom collections like "Kitchen Equipment" or "Office Supplies".
    """
    __tablename__ = 'collections'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    collection_type = db.Column(db.String(50), default='custom', index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    data = db.Column(JSONB, default=lambda: {})  # Collection metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_public = db.Column(db.Boolean, default=False)
    
    # Relationships
    objects = db.relationship('Object', secondary=collection_objects,
                              lazy='dynamic', backref=db.backref('collections', lazy='dynamic'))
    
    def __repr__(self):
        return f"<Collection {self.name}>"
    
    def add_object(self, obj):
        """Add an object to this collection"""
        if not self.has_object(obj):
            self.objects.append(obj)
    
    def remove_object(self, obj):
        """Remove an object from this collection"""
        if self.has_object(obj):
            self.objects.remove(obj)
    
    def has_object(self, obj):
        """Check if object is in this collection"""
        return self.objects.filter(collection_objects.c.object_id == obj.id).count() > 0


