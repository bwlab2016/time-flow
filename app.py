from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from zoneinfo import ZoneInfo

app = Flask(__name__)

# 配置数据库
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.urandom(24)

db = SQLAlchemy(app)

# 任务模型
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo('Asia/Shanghai')))

# 时间轴记录模型
class TimeBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    date = db.Column(db.Date, nullable=False)  # 这个字段可能需要重新考虑，因为有跨天的情况

# 首页路由
@app.route('/')
def index():
    return render_template('index.html')

# API路由
@app.route('/api/tasks', methods=['GET', 'POST', 'PUT'])
def handle_tasks():
    if request.method == 'GET':
        date = request.args.get('date')
        query_date = datetime.strptime(date, '%Y-%m-%d').date()
        
        # 获取在查询日期有时间块的任务ID
        # 1. date 字段等于查询日期的时间块
        # 2. 时间范围包含查询日期的时间块
        tasks_with_blocks = db.session.query(TimeBlock.task_id)\
            .filter(
                db.or_(
                    TimeBlock.date == query_date,  # 直接匹配日期
                    db.and_(  # 或者时间范围包含查询日期
                        db.cast(TimeBlock.start_time, db.Date) <= query_date,
                        db.cast(TimeBlock.end_time, db.Date) >= query_date
                    )
                )
            )\
            .distinct()\
            .subquery()
        
        # 查询任务：
        # 1. 未完成的任务
        # 2. 已完成的任务，且在查询日期有时间块
        tasks = Task.query.filter(
            db.or_(
                ~Task.completed,  # 未完成的任务
                Task.id.in_(tasks_with_blocks)  # 有时间块的任务
            )
        ).all()
        
        return jsonify([{
            'id': task.id,
            'title': task.title,
            'completed': task.completed,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None
        } for task in tasks])
    elif request.method == 'POST':
        data = request.get_json()
        task = Task(title=data['title'])
        db.session.add(task)
        db.session.commit()
        return jsonify({
            'id': task.id,
            'title': task.title,
            'completed': task.completed
        })

@app.route('/api/tasks/<int:task_id>/complete', methods=['PUT'])
def complete_task(task_id):
    task = Task.query.get_or_404(task_id)
    data = request.get_json()
    task.completed = data['completed']
    # 如果是标记完成，设置完成时间；如果是取消完成，清除完成时间
    task.completed_at = datetime.now(ZoneInfo('Asia/Shanghai')) if data['completed'] else None
    db.session.commit()
    return jsonify({
        'id': task.id,
        'title': task.title,
        'completed': task.completed,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None
    })

@app.route('/api/timeblocks', methods=['GET', 'POST'])
def handle_timeblocks():
    if request.method == 'GET':
        task_id = request.args.get('task_id')
        date = request.args.get('date')
        query_date = datetime.strptime(date, '%Y-%m-%d').date()
        
        # 修改查询逻辑，查找：
        # 1. date 字段等于查询日期的时间块
        # 2. 时间范围包含查询日期的时间块
        timeblocks = TimeBlock.query.filter(
            TimeBlock.task_id == task_id,
            db.or_(
                TimeBlock.date == query_date,  # 直接匹配日期
                db.and_(  # 或者时间范围包含查询日期
                    db.cast(TimeBlock.start_time, db.Date) <= query_date,
                    db.cast(TimeBlock.end_time, db.Date) >= query_date
                )
            )
        ).all()
        
        return jsonify([{
            'id': block.id,
            'start_time': block.start_time.astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
            'end_time': block.end_time.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
        } for block in timeblocks])
    elif request.method == 'POST':
        data = request.get_json()
        # 将前端发来的ISO格式时间转换为北京时间
        start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai'))
        end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai'))
        date = start_time.date()
        
        # 修改重叠检查逻辑，考虑跨天情况
        existing_blocks = TimeBlock.query.filter(
            TimeBlock.task_id == data['task_id'],
            db.or_(
                TimeBlock.date == date,
                db.and_(
                    db.cast(TimeBlock.start_time, db.Date) <= end_time.date(),
                    db.cast(TimeBlock.end_time, db.Date) >= start_time.date()
                )
            ),
            TimeBlock.start_time < end_time,
            TimeBlock.end_time > start_time
        ).first()
        
        if existing_blocks:
            return jsonify({'error': '时间段重叠'}), 400
            
        timeblock = TimeBlock(
            task_id=data['task_id'],
            start_time=start_time,
            end_time=end_time,
            date=date
        )
        db.session.add(timeblock)
        db.session.commit()
        return jsonify({
            'id': timeblock.id,
            'start_time': timeblock.start_time.astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
            'end_time': timeblock.end_time.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
        })

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    # 删除任务相关的所有时间块
    TimeBlock.query.filter_by(task_id=task_id).delete()
    # 删除任务
    db.session.delete(task)
    db.session.commit()
    return '', 204

@app.route('/api/stats', methods=['GET'])
def get_stats():
    date = request.args.get('date')
    query_date = datetime.strptime(date, '%Y-%m-%d').date()
    
    # 获取当天的任务和时间块
    tasks_with_blocks = db.session.query(TimeBlock.task_id)\
        .filter(
            db.or_(
                TimeBlock.date == query_date,
                db.and_(
                    db.cast(TimeBlock.start_time, db.Date) <= query_date,
                    db.cast(TimeBlock.end_time, db.Date) >= query_date
                )
            )
        )\
        .distinct()\
        .subquery()

    tasks = Task.query.filter(
        db.or_(
            ~Task.completed,
            Task.id.in_(tasks_with_blocks)
        )
    ).all()

    # 计算统计信息
    total_tasks = len(tasks)
    completed_tasks = sum(1 for task in tasks if task.completed)
    completion_rate = round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0)

    # 计算工作时长
    timeblocks = TimeBlock.query.filter(
        db.or_(
            TimeBlock.date == query_date,
            db.and_(
                db.cast(TimeBlock.start_time, db.Date) <= query_date,
                db.cast(TimeBlock.end_time, db.Date) >= query_date
            )
        )
    ).all()

    total_work_minutes = 0
    for block in timeblocks:
        # 确保只计算查询日期的时间
        start = max(block.start_time, datetime.combine(query_date, datetime.min.time()))
        end = min(block.end_time, datetime.combine(query_date + timedelta(days=1), datetime.min.time()))
        duration = (end - start).total_seconds() / 60
        total_work_minutes += duration

    total_work_hours = round(total_work_minutes / 60, 1)
    avg_work_hours = round(total_work_hours / total_tasks, 1) if total_tasks > 0 else 0

    return jsonify({
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'completion_rate': completion_rate,
        'total_work_hours': total_work_hours,
        'avg_work_hours': avg_work_hours
    })

@app.route('/api/timeblocks/<int:block_id>', methods=['DELETE'])
def delete_timeblock(block_id):
    timeblock = TimeBlock.query.get_or_404(block_id)
    db.session.delete(timeblock)
    db.session.commit()
    return '', 204

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)