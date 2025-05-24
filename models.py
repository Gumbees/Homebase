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


